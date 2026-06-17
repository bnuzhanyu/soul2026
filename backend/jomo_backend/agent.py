from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Iterator
from urllib.parse import quote

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, UserMessage, query

try:
    from claude_agent_sdk import ThinkingBlock, ToolResultBlock, ToolUseBlock
except ImportError:  # pragma: no cover - sdk version compatibility
    ThinkingBlock = ToolResultBlock = ToolUseBlock = ()  # type: ignore

from .strategy import current_progress_summary
from .oss_storage import upload_file


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = Path(os.getenv("JOMO_AGENT_RUN_DIR", ROOT / ".run" / "jomo-agent")).resolve()
CLAUDE_DIR = Path(os.getenv("JOMO_CLAUDE_DIR", ROOT / ".run" / "claude")).resolve()
ASSETS_DIR = Path(os.getenv("JOMO_AGENT_ASSETS_DIR", ROOT / ".run" / "jomo-assets")).resolve()
LOCAL_AGENT_SKILLS_DIR = ROOT / "backend" / "agent_skills"
DEFAULT_MODEL = "claude-sonnet-4-20250514"


async def stream_agent_events(payload: dict[str, Any]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    partner = payload.get("partner") or {}
    skill = payload.get("skill") or {}
    profile = payload.get("profile") or {}
    model = (os.getenv("CLAUDE_AGENT_MODEL") or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL).removeprefix("anthropic:")
    base_session_id = stable_session_id(partner, profile=profile)
    session_id = agent_session_id(base_session_id, skill)
    session_dir = RUN_DIR / safe_key(session_id)
    session_store_dir = session_dir / "sessions"
    asset_dir = ASSETS_DIR / safe_key(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    sync_agent_skills(skill)
    before_assets = asset_snapshot(asset_dir)

    required_skills = list(skill.get("agentSkills") or [])
    has_history = jsonl_session_has_history(session_store_dir, session_id)
    skills_ready = session_has_required_skills(session_store_dir, session_id, required_skills)
    can_resume = has_history and skills_ready
    reply_parts: list[str] = []

    yield "agent.session", {
        "provider": "anthropic",
        "model": model or "default",
        "sessionId": session_id,
        "baseSessionId": base_session_id,
        "agentSkills": required_skills,
        "resume": can_resume,
        "resumeBlockedReason": "" if can_resume or not has_history else "session skill listing is missing required skills",
        "sessionDir": str(session_dir),
    }

    def on_stderr(line: str) -> None:
        text = str(line or "").strip()
        if text:
            print(f"[jomo-agent] {text}", file=sys.stderr, flush=True)

    async for message in query(
        prompt=build_prompt(payload),
        options=ClaudeAgentOptions(
            system_prompt=system_prompt(),
            model=model,
            cwd=str(session_dir),
            session_id=None if can_resume else session_id,
            resume=session_id if can_resume else None,
            session_store=JsonlSessionStore(session_store_dir),
            session_store_flush="eager",
            env=claude_env(model, asset_dir=asset_dir),
            cli_path=claude_cli_path(),
            max_turns=int(os.getenv("JOMO_AGENT_MAX_TURNS", "2")),
            effort=os.getenv("JOMO_AGENT_EFFORT", "low"),
            allowed_tools=["Skill", "Bash"] if skill.get("agentSkills") else [],
            disallowed_tools=["Write", "Edit", "MultiEdit", "NotebookEdit"],
            setting_sources=["user"],
            skills=list(skill.get("agentSkills") or []),
            stderr=on_stderr,
        ),
    ):
        if isinstance(message, AssistantMessage):
            for event, data in iter_block_events(message.content, include_text=True, reply_parts=reply_parts):
                yield event, data
        elif isinstance(message, UserMessage):
            for event, data in iter_block_events(message.content, include_text=False, reply_parts=reply_parts):
                yield event, data
        elif isinstance(message, ResultMessage):
            yield "agent.result", {
                "sessionId": message.session_id,
                "stopReason": message.stop_reason,
                "isError": message.is_error,
                "usage": message.usage or {},
            }

    raw_reply = "".join(reply_parts)
    html_blocks = extract_html_blocks(raw_reply)
    for html in html_blocks:
        yield "html", {"html": html, "source": "ai", "kind": "html"}
    markdown_blocks = extract_markdown_blocks(raw_reply)
    for markdown in markdown_blocks:
        yield "markdown", {"markdown": markdown, "source": "ai", "kind": "markdown"}
    for item in new_asset_events(asset_dir, before_assets, session_id, username=str(profile.get("username") or "agent")):
        yield item["type"], item["data"]
    yield "ai.raw", {
        "provider": "anthropic",
        "model": model or "default",
        "sessionId": session_id,
        "reply": raw_reply,
        "htmlBlocks": html_blocks,
        "markdownBlocks": markdown_blocks,
    }


def has_ai_config() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def iter_block_events(
    blocks: Any,
    *,
    include_text: bool,
    reply_parts: list[str],
) -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(blocks, str):
        return
    for block in blocks or []:
        if include_text and isinstance(block, TextBlock) and block.text:
            reply_parts.append(block.text)
            yield "agent.assistant_text", {"text": block.text, "kind": infer_text_kind(block.text)}
            visible = strip_rich_contracts(block.text)
            for chunk in re.findall(r"[\s\S]{1,4}", visible) or ([visible] if visible else []):
                yield "token", {"text": chunk}
        elif ThinkingBlock and isinstance(block, ThinkingBlock):
            thinking = str(getattr(block, "thinking", "") or "")
            yield "agent.thinking", {"summary": "模型正在整理回复策略和下一步动作。", "chars": len(thinking)}
        elif is_tool_use_block(block):
            yield "agent.tool_use", {
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": normalize_tool_input(getattr(block, "input", {})),
            }
        elif is_tool_result_block(block):
            yield "agent.tool_result", {
                "toolUseId": getattr(block, "tool_use_id", "") or getattr(block, "toolUseId", ""),
                "isError": bool(getattr(block, "is_error", False) or getattr(block, "isError", False)),
                "content": normalize_tool_result_content(getattr(block, "content", "")),
            }


def is_tool_use_block(block: Any) -> bool:
    if ToolUseBlock and isinstance(block, ToolUseBlock):
        return True
    return block.__class__.__name__ in {"ToolUseBlock", "ServerToolUseBlock"}


def is_tool_result_block(block: Any) -> bool:
    if ToolResultBlock and isinstance(block, ToolResultBlock):
        return True
    return block.__class__.__name__ in {"ToolResultBlock", "ServerToolResultBlock"}


def provider_info() -> dict[str, Any]:
    return {
        "enabled": has_ai_config(),
        "provider": "anthropic",
        "model": os.getenv("CLAUDE_AGENT_MODEL") or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL,
        "python": sys.executable,
    }


def build_prompt(payload: dict[str, Any]) -> str:
    profile = payload.get("profile") or {}
    partner = payload.get("partner") or {}
    skill = payload.get("skill") or {}
    user_text = str(payload.get("userText") or "")
    attachment = payload.get("attachment")
    messages = [
        msg for msg in (partner.get("messages") or [])[-8:]
        if msg.get("type") == "text" and msg.get("content")
    ]
    history = "\n".join(
        f"{'JOMO' if msg.get('role') == 'assistant' else '用户'}：{str(msg.get('content'))[:500]}"
        for msg in messages
    )
    media_history = recent_media_summary(partner)
    attachment_note = ""
    if attachment:
        attachment_note = (
            "用户刚上传了练习素材。请优先基于素材类型和用户目标反馈；"
            "如果是图片，附件 url 是用户本次作品图。评分时若最近有 JOMO 生成的目标图/参考图，需要一起传给图片理解工具做对比；"
            "如果当前模型不能直接读取素材内容，就明确说明只能基于用户描述和上传动作反馈，不虚构细节。\n"
            f"附件信息：{json.dumps(attachment, ensure_ascii=False)[:1000]}\n"
        )
    return "\n".join([
        f"用户名：{profile.get('username') or 'guest'}",
        f"显示名：{profile.get('displayName') or profile.get('username') or 'JOMO 用户'}",
        f"近期目标：{profile.get('goal') or '每天轻松完成一个小练习'}",
        f"当前伙伴：{partner.get('name') or skill.get('name') or 'JOMO 伙伴'}",
        f"学习技能：{skill.get('name') or ''}",
        f"标签：{'、'.join(skill.get('tags') or [])}",
        f"学习技能策略：{skill.get('strategy') or ''}",
        f"学习技能语气：{skill.get('tone') or ''}",
        f"目标图生成提示：{skill.get('targetPrompt') or ''}",
        f"评分标准：{skill.get('reviewRubric') or ''}",
        f"此学习技能允许调用的 agent skill：{', '.join(skill.get('agentSkills') or []) or '无'}",
        f"今日挑战：{(partner.get('plan') or {}).get('challenge') or skill.get('starter') or ''}",
        f"训练计划：\n{json.dumps((skill.get('plan') or {}).get('goals', []), ensure_ascii=False)[:3000]}",
        f"当前进度：\n{current_progress_summary(partner, skill)}",
        f"最近 compact：\n{json.dumps((partner.get('compacts') or [])[-3:], ensure_ascii=False)[:1200]}",
        f"最近对话：\n{history or '暂无'}",
        f"最近素材：\n{media_history or '暂无'}",
        "",
        f"{attachment_note}用户这次说：{user_text}",
    ])


def system_prompt() -> str:
    return "\n".join([
        "你是 JOMO，一个温暖、轻量、可爱的 AI 技能伙伴，帮用户用小技能成长对抗 FOMO。",
        "你既是耐心出色的教练，也是温柔体贴的伙伴：能看见用户的努力，也能指出一个清楚的小改进。",
        "回复必须短，通常 1-3 句话；不要展示长推理，不要写长教程。",
        "每次输出前先决定内容类型：text、image、audio、markdown、html。普通聊天用 text；结构化说明可用 markdown；互动控件用 html。",
        "语气有人味、松弛、可爱但不幼稚，像陪用户一起练的小伙伴。",
        "不要说冷冰冰的话，比如“今天先别追太多，我们只完成”。",
        "如果用户汇报数量，先认可，再给一个动作质量或下一步小建议。",
        "如果用户点击或说“开始本关卡”“开始今天学习”，直接生成本次训练内容：包含一个很小的任务、判断标准、需要用户反馈的结果；适合互动时可输出 html 或 markdown 卡片。",
        "如果学习技能是简笔画/绘画类，开始学习时优先生成或提供一张今日目标图/参考图；后续用户上传作品图评分时，把目标图 URL 和用户作品 URL 一起传给图片理解工具。",
        "如果用户表达焦虑，先接住情绪，再给一个很小、可立即完成的动作。",
        "如果用户上传图片且当前学习技能允许 mimo-image-understanding，先调用该 agent skill 读取图片 URL，再按目标给简短评分或观察建议。",
        "调用 mimo-image-understanding 时，Skill 工具的 args 必须是严格 JSON 字符串，不要传自然语言。格式：{\"mode\":\"single|scoring|compare\",\"imageUrls\":[\"用户作品图URL\"],\"targetImageUrls\":[\"今日目标图URL\"],\"learningGoal\":\"今天的目标\",\"rubric\":\"是否画对、完成度、美观度和一个小建议\"}。",
        "简笔画评分时，如果有今日目标图/参考图，必须使用 mode=scoring，并传 targetImageUrls；如果没有目标图，也要传 JSON，说明只做单图观察。",
        "如果没有真实读图结果，就明确只基于用户描述和上传动作反馈，不虚构图片细节。",
        "你可以生成 HTML 互动卡片，但必须放在 <jomo-html> 和 </jomo-html> 之间；普通回复不要写 HTML。",
        "你可以生成 Markdown 卡片，但必须放在 <jomo-markdown> 和 </jomo-markdown> 之间；普通回复不要包 Markdown。",
        "HTML 只能使用 div/p/strong/span/button/label/input/textarea/audio，不要 script/style/iframe，不要内联事件。",
        "按钮使用 data-jomo-choice=\"要发给你的文字\"；速读可使用 data-reading-* 属性；音频可用 audio controls。",
        "可用技能：生成 HTML 卡片、根据结果评价、通过图和目标打分、生成一段和弦 mp3（如工具可用时）、生成训练素材图片（通过 seedream-game-assets skill，如工具可用时）。",
        "如果需要生图，调用 seedream-game-assets skill；不要把图片字节写进回复，只把生成结果说明清楚。",
        "只能调用当前学习技能允许的 agent skill；如果没有被允许，就用文字说明替代。",
    ])


def extract_html_blocks(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"<jomo-html>([\s\S]*?)</jomo-html>", text, re.I):
        html = sanitize_generated_html(match.group(1).strip())
        if html:
            blocks.append(html)
    return blocks


def extract_markdown_blocks(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"<jomo-markdown>([\s\S]*?)</jomo-markdown>", text, re.I):
        markdown = match.group(1).strip()
        if markdown:
            blocks.append(markdown[:6000])
    return blocks


def strip_rich_contracts(text: str) -> str:
    value = re.sub(r"<jomo-html>[\s\S]*?(?:</jomo-html>|$)", "", text, flags=re.I)
    value = re.sub(r"<jomo-markdown>[\s\S]*?(?:</jomo-markdown>|$)", "", value, flags=re.I)
    return value.strip()


def infer_text_kind(text: str) -> str:
    if re.search(r"<jomo-html>", text, re.I):
        return "html"
    if re.search(r"<jomo-markdown>", text, re.I):
        return "markdown"
    return "text"


def normalize_tool_input(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    args = normalized.get("args")
    if isinstance(args, str):
        stripped = args.strip()
        normalized["argsFormat"] = "json" if stripped.startswith("{") else "text"
        if stripped.startswith("{"):
            try:
                normalized["parsedArgs"] = json.loads(stripped)
            except json.JSONDecodeError:
                normalized["argsFormat"] = "invalid-json"
    return normalized


def normalize_tool_result_content(value: Any) -> dict[str, Any]:
    raw = value
    if isinstance(raw, list):
        text_parts = []
        blocks = []
        for item in raw:
            if isinstance(item, dict):
                blocks.append(item)
                if item.get("text"):
                    text_parts.append(str(item.get("text")))
            else:
                text_parts.append(str(item))
        text = "\n".join(part for part in text_parts if part).strip()
    elif isinstance(raw, dict):
        blocks = [raw]
        text = str(raw.get("text") or raw.get("content") or raw)
    else:
        blocks = []
        text = str(raw or "")

    parsed: Any = None
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
    return {
        "text": text[:5000],
        "parsed": parsed,
        "blocks": blocks[:8],
        "truncated": len(text) > 5000,
    }


def recent_media_summary(partner: dict[str, Any]) -> str:
    rows = []
    for msg in (partner.get("messages") or [])[-16:]:
        msg_type = msg.get("type")
        url = msg.get("url")
        if msg_type not in {"image", "audio", "html", "markdown"} and not url:
            continue
        role = "JOMO" if msg.get("role") == "assistant" else "用户"
        content = str(msg.get("content") or "")[:240]
        if url:
            rows.append(f"- {role} {msg_type}: {content} URL={url}")
        elif msg_type in {"html", "markdown"}:
            rows.append(f"- {role} {msg_type}: {content[:300]}")
    return "\n".join(rows[-8:])


def sanitize_generated_html(value: str) -> str:
    value = re.sub(r"</?(script|style|iframe|object|embed|link|meta)[^>]*>", "", value, flags=re.I)
    value = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", value, flags=re.I | re.S)
    value = re.sub(r"javascript:", "", value, flags=re.I)
    return value[:6000]


def stable_session_id(partner: dict[str, Any], *, profile: dict[str, Any] | None = None) -> str:
    profile = profile or {}
    raw = ":".join([
        str(profile.get("username") or "guest"),
        str(partner.get("skillId") or "learning-skill"),
        str(partner.get("id") or "partner"),
        str(partner.get("sessionId") or "session"),
    ])
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jomo:{raw}"))


def agent_session_id(base_session_id: str, skill: dict[str, Any]) -> str:
    agent_skills = sorted(str(item) for item in (skill.get("agentSkills") or []) if str(item).strip())
    if not agent_skills:
        return base_session_id
    signature = ",".join(agent_skills)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jomo-agent:{base_session_id}:skills:{signature}"))


def safe_key(value: str) -> str:
    cleaned = re.sub(r"[^\w_.-]+", "-", str(value).strip(), flags=re.UNICODE).strip("-")[:96]
    return cleaned or hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


def claude_cli_path() -> Path | None:
    explicit = os.getenv("JOMO_CLAUDE_CLI") or os.getenv("CLAUDE_CLI_PATH")
    if explicit and Path(explicit).expanduser().is_file():
        return Path(explicit).expanduser()
    found = shutil.which("claude")
    return Path(found) if found else None


def claude_env(model: str | None, *, asset_dir: Path | None = None) -> dict[str, str]:
    env = {
        "CLAUDE_CONFIG_DIR": str(CLAUDE_DIR),
        "GAME_AGENT_SEEDREAM_SCRIPT": str(CLAUDE_DIR / "skills" / "seedream-game-assets" / "scripts" / "generate_and_crop.py"),
        "JOMO_MIMO_IMAGE_UNDERSTANDING_SCRIPT": str(CLAUDE_DIR / "skills" / "mimo-image-understanding" / "scripts" / "mimo_image_understanding.py"),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": os.getenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1"),
        "DISABLE_TELEMETRY": os.getenv("DISABLE_TELEMETRY", "1"),
    }
    if asset_dir is not None:
        env["GAME_AGENT_DRAFT_ASSETS_DIR"] = str(asset_dir)
    for key in (
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
        "ARK_API_KEY", "SEEDREAM_MODEL", "SEEDREAM_SIZE", "SEEDREAM_BASE_URL",
        "MIMO_API_KEY", "MIMO_ANTHROPIC_BASE_URL", "MIMO_ANTHROPIC_VERSION", "MIMO_IMAGE_MODEL",
    ):
        if os.getenv(key):
            env[key] = os.getenv(key, "")
    base_url = (env.get("ANTHROPIC_BASE_URL") or "").lower()
    if base_url and "anthropic.com" not in base_url and env.get("ANTHROPIC_API_KEY") and not env.get("ANTHROPIC_AUTH_TOKEN"):
        env["ANTHROPIC_AUTH_TOKEN"] = env["ANTHROPIC_API_KEY"]
    if model:
        env["ANTHROPIC_MODEL"] = model
        env["ANTHROPIC_SMALL_FAST_MODEL"] = model
    return env


def sync_agent_skills(skill: dict[str, Any]) -> None:
    target_root = CLAUDE_DIR / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    for name in skill.get("agentSkills") or []:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(name)):
            continue
        source = LOCAL_AGENT_SKILLS_DIR / str(name)
        target = target_root / str(name)
        if not source.exists():
            continue
        shutil.copytree(source, target, dirs_exist_ok=True)


def asset_snapshot(asset_dir: Path) -> set[str]:
    if not asset_dir.exists():
        return set()
    return {str(path.relative_to(asset_dir)) for path in asset_dir.rglob("*") if path.is_file()}


def new_asset_events(asset_dir: Path, before: set[str], session_id: str, *, username: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for relative in sorted(asset_snapshot(asset_dir) - before):
        suffix = Path(relative).suffix.lower()
        file_path = asset_dir / relative
        uploaded = upload_generated_asset(file_path, username=username)
        fallback_url = f"/api/assets/{safe_key(session_id)}/{quote(relative)}"
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            events.append({"type": "image", "data": {"kind": "image", "url": (uploaded or {}).get("url") or fallback_url, "path": relative, "oss": uploaded}})
        if suffix in {".mp3", ".wav", ".m4a", ".ogg"}:
            events.append({"type": "audio", "data": {"kind": "audio", "url": (uploaded or {}).get("url") or fallback_url, "path": relative, "oss": uploaded}})
    return events


def upload_generated_asset(path: Path, *, username: str) -> dict[str, Any] | None:
    try:
        return upload_file(path, username=username, kind="generated")
    except Exception as error:
        print(f"[jomo-agent] OSS upload skipped: {str(error)[:300]}", file=sys.stderr, flush=True)
        return None


def jsonl_session_has_history(store_dir: Path, session_id: str) -> bool:
    if not store_dir.exists():
        return False
    for project_dir in store_dir.iterdir():
        if not project_dir.is_dir():
            continue
        main_jsonl = project_dir / f"{session_id}.jsonl"
        if main_jsonl.is_file() and main_jsonl.stat().st_size > 0:
            return True
        nested = project_dir / session_id
        if nested.is_dir() and any(nested.iterdir()):
            return True
    return False


def session_has_required_skills(store_dir: Path, session_id: str, required_skills: list[str]) -> bool:
    required = {str(item) for item in required_skills if str(item).strip()}
    if not required:
        return True
    listings = []
    for path in session_jsonl_paths(store_dir, session_id):
        try:
            text = path.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if '"skill_listing"' not in line:
                continue
            listings.append(line)
    if not listings:
        return True
    joined = "\n".join(listings)
    return all(skill_name in joined for skill_name in required)


def session_jsonl_paths(store_dir: Path, session_id: str) -> list[Path]:
    if not store_dir.exists():
        return []
    paths: list[Path] = []
    for project_dir in store_dir.iterdir():
        if not project_dir.is_dir():
            continue
        main_jsonl = project_dir / f"{session_id}.jsonl"
        if main_jsonl.is_file():
            paths.append(main_jsonl)
        nested = project_dir / session_id
        if nested.is_dir():
            paths.extend(path for path in nested.rglob("*.jsonl") if path.is_file())
    return paths


class JsonlSessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _project_dir(self, project_key: str) -> Path:
        return self.root / safe_key(project_key)

    def _path_for(self, key: dict[str, Any]) -> Path:
        session_id = str(key["session_id"])
        subpath = str(key.get("subpath") or "").strip().replace("\\", "/").strip("/")
        base = self._project_dir(str(key["project_key"]))
        if subpath:
            return base / session_id / f"{safe_key(subpath)}.jsonl"
        return base / f"{session_id}.jsonl"

    async def append(self, key: dict[str, Any], entries: list[dict[str, Any]]) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        if path.exists():
            for line in path.read_text("utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("uuid"):
                    seen.add(item["uuid"])
        with path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                entry_uuid = entry.get("uuid")
                if entry_uuid and entry_uuid in seen:
                    continue
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if entry_uuid:
                    seen.add(entry_uuid)

    async def load(self, key: dict[str, Any]) -> list[dict[str, Any]] | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        entries = []
        for line in path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries or None

    async def list_sessions(self, project_key: str) -> list[dict[str, Any]]:
        project_dir = self._project_dir(project_key)
        if not project_dir.exists():
            return []
        return [
            {"session_id": path.stem, "mtime": int(path.stat().st_mtime * 1000)}
            for path in project_dir.glob("*.jsonl")
        ]

    async def list_subkeys(self, key: dict[str, Any]) -> list[str]:
        session_dir = self._project_dir(str(key["project_key"])) / str(key["session_id"])
        if not session_dir.exists():
            return []
        return [path.stem for path in session_dir.glob("*.jsonl")]

    async def delete(self, key: dict[str, Any]) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()
        if not key.get("subpath"):
            session_dir = self._project_dir(str(key["project_key"])) / str(key["session_id"])
            if session_dir.exists():
                shutil.rmtree(session_dir)
