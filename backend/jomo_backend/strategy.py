from __future__ import annotations

import html
import random
import re
import time
from typing import Any

from .skills import flatten_nodes


def create_partner_plan(*, profile: dict[str, Any] | None = None, skill: dict[str, Any]) -> dict[str, Any]:
    profile = profile or {}
    first_goal = (skill.get("plan") or {}).get("goals", [{}])[0]
    first_milestone = (first_goal.get("milestones") or [{}])[0]
    name = profile.get("displayName") or profile.get("username") or "你"
    return {
        "title": (skill.get("plan") or {}).get("title") or f"{skill['name']}训练计划",
        "challenge": skill.get("starter") or first_milestone.get("description") or "完成一个轻量练习",
        "reason": f"{name}，我们先把第一个小关卡练顺。慢慢来，JOMO 会陪你把进度变成看得见的小星星。",
        "currentGoalId": first_goal.get("id"),
        "currentMilestoneId": first_milestone.get("id"),
        "goals": (skill.get("plan") or {}).get("goals", []),
        "createdAt": int(time.time() * 1000),
    }


def create_custom_skill_prompt(*, username: str, title: str, target_level: str, tags: list[str] | None = None) -> str:
    tag_text = "、".join(tags or []) or "用户自定义"
    return f"""
你是 JOMO 的课程设计 agent。请为用户创建一份可执行的技能训练大纲。

用户：{username}
技能名称：{title}
目标等级：{target_level or "入门到稳定练习"}
标签：{tag_text}

要求：
1. 输出严格 JSON，不要 Markdown。
2. plan 按 10 到 15 天作为一个节点，拆成 2-4 个大目标。
3. 每个大目标是阶段性成果，包含 days、outcome 和 2-4 个小目标 milestones。
4. 小目标必须服务于对应大目标，能被用户提前结束、跳过或重置。
5. 语气适合 JOMO：耐心、具体、温柔、不制造焦虑。
6. JSON 结构：
{{
  "id": "英文短横线id",
  "name": "中文技能名",
  "tags": ["标签"],
  "image": "可为空字符串",
  "strategy": "coaching",
  "tone": "一句语气说明",
  "starter": "第一次训练任务",
  "agentSkills": ["允许使用的 agent skill 名称，没有则为空数组"],
  "plan": {{
    "title": "训练计划标题",
    "goals": [
      {{
        "id": "g1",
        "title": "大目标",
        "days": "1-15",
        "outcome": "阶段性成果",
        "milestones": [
          {{"id":"g1-m1","title":"小目标","description":"如何练"}}
        ]
      }}
    ]
  }}
}}
""".strip()


def fallback_custom_skill(*, title: str, target_level: str, tags: list[str] | None = None) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or f"custom-{int(time.time())}"
    return {
        "id": f"custom-{slug}"[:48],
        "name": title[:24] or "自定义技能",
        "tags": tags or ["自定义"],
        "image": "https://images.unsplash.com/photo-1499750310107-5fef28a66643?auto=format&fit=crop&w=480&q=80",
        "strategy": "coaching",
        "tone": "耐心、具体、像温柔教练一样陪用户拆小步",
        "starter": f"先完成一次 10 分钟的{title}轻练习，目标是感受节奏。",
        "agentSkills": [],
        "plan": {
            "title": f"{target_level or '入门'} · {title}训练大纲",
            "goals": [
                {
                    "id": "g1",
                    "title": "建立基础动作",
                    "days": "1-15",
                    "outcome": "能稳定完成一次基础练习。",
                    "milestones": [
                        {"id": "g1-m1", "title": "认识标准", "description": "了解这个技能最重要的 3 个判断标准。"},
                        {"id": "g1-m2", "title": "完成首练", "description": "做一次 10 分钟练习并记录感受。"},
                    ],
                },
                {
                    "id": "g2",
                    "title": "形成个人节奏",
                    "days": "16-30",
                    "outcome": "能独立选择练习内容并完成复盘。",
                    "milestones": [
                        {"id": "g2-m1", "title": "复盘反馈", "description": "说出一个做得好的点和一个想改的小点。"},
                        {"id": "g2-m2", "title": "小作品/小成果", "description": "完成一个可以展示的阶段成果。"},
                    ],
                },
            ],
        },
    }


def create_chat_events(*, profile: dict[str, Any] | None = None, partner: dict[str, Any] | None = None, user_text: str = "", attachment: Any = None, skill: dict[str, Any]) -> list[dict[str, Any]]:
    profile = profile or {}
    partner = partner or {}
    events = [{
        "type": "agent.started",
        "data": {"partnerId": partner.get("id"), "skill": skill["name"], "strategy": skill["strategy"], "userText": user_text},
    }]

    if skill["strategy"] == "timed_reading" and wants_exercise(user_text):
        exercise = create_speed_reading_exercise(profile=profile, partner=partner)
        events.extend(tokens_for("来，开一张小速读卡。读完不用紧张，选题就像摸摸今天的理解小温度。"))
        events.append({"type": "html", "data": {"html": exercise["html"], "exercise": exercise}})
        return events

    if wants_start_learning(user_text):
        card = create_today_learning_card(partner=partner, skill=skill)
        events.extend(tokens_for("好呀，今天的小练习已经摆好啦。先照着卡片做一小段，做完回来找我评一下。"))
        events.append({"type": "html", "data": {"html": card, "kind": "html"}})
        return events

    action_reply = progress_action_reply(user_text, partner, skill)
    if action_reply:
        events.extend(tokens_for(action_reply["text"]))
        events.append({"type": "progress", "data": action_reply["progress"]})
        events.append({"type": "compact", "data": {"reason": action_reply["progress"].get("action"), "summary": action_reply["text"]}})
        return events

    progress: dict[str, Any] = {}
    if attachment:
        reply = image_reply(skill)
        progress["evidence"] = f"上传了 {skill['name']} 练习图片，并收到一次反馈"
    elif count := extract_count(user_text):
        reply = count_reply(skill, count)
        progress["evidence"] = f"完成 {count} {skill['name']} 练习"
        progress["completeNext"] = True
    elif is_anxiety(user_text):
        challenge = (partner.get("plan") or {}).get("challenge") or skill["starter"]
        reply = f"我听到你有点急。先把眼睛从别人那里收回来一点点，我们陪今天的自己做这个：{challenge}"
    elif re.search(r"^[ABCDabcd]$", user_text.strip()):
        reply = "收到选择啦。我会按这次答案给你记一次理解训练，下一次我们再把判断变得更稳。"
        progress["evidence"] = f"完成一次 {skill['name']} 选择题练习"
        progress["completeNext"] = True
    elif wants_options(user_text):
        events.extend(tokens_for("给你两条小路，挑顺眼的那条就好。"))
        events.append({"type": "html", "data": {"html": choice_card_html()}})
        return events
    else:
        challenge = (partner.get("plan") or {}).get("challenge") or skill["starter"]
        reply = f"好呀，我在。今天我们就抓一个小小的点：{challenge}"

    events.extend(tokens_for(reply))
    if progress:
        events.append({"type": "progress", "data": progress})
    return events


def should_use_local_chat_strategy(*, user_text: str = "", skill: dict[str, Any]) -> bool:
    return (
        (skill["strategy"] == "timed_reading" and wants_exercise(user_text))
        or wants_start_learning(user_text)
        or wants_options(user_text)
        or bool(progress_action_reply(user_text, {}, skill))
    )


def create_today_learning_card(*, partner: dict[str, Any], skill: dict[str, Any]) -> str:
    progress = partner.get("progress") or {}
    current_id = progress.get("currentMilestoneId") if isinstance(progress, dict) else ""
    milestone = find_milestone(skill, current_id) or first_milestone(skill) or {}
    title = html.escape(str(milestone.get("title") or skill.get("starter") or "今天的小练习"))
    description = html.escape(str(milestone.get("description") or skill.get("starter") or "完成一个轻量练习，然后告诉我结果。"))
    standard = html.escape(standard_for(skill))
    return f"""
    <div class="choice-card start-card">
      <strong>今日小关卡 · {title}</strong>
      <p>{description}</p>
      <p><strong>看这一个标准：</strong>{standard}</p>
      <button data-jomo-choice="我做完了，帮我评价一下">我做完了，帮我评价一下</button>
      <button data-jomo-choice="给我换一个更轻松的版本">换一个轻松版</button>
    </div>
    """


def find_milestone(skill: dict[str, Any], milestone_id: str | None) -> dict[str, Any] | None:
    if not milestone_id:
        return None
    for goal in (skill.get("plan") or {}).get("goals", []):
        for milestone in goal.get("milestones", []):
            if milestone.get("id") == milestone_id:
                return milestone
    return None


def first_milestone(skill: dict[str, Any]) -> dict[str, Any] | None:
    for goal in (skill.get("plan") or {}).get("goals", []):
        milestones = goal.get("milestones") or []
        if milestones:
            return milestones[0]
    return None


def standard_for(skill: dict[str, Any]) -> str:
    strategy = skill.get("strategy")
    if strategy == "creative_review":
        return "线条或形状里有一个地方比上次更清楚。"
    if strategy == "audio_quiz":
        return "说出你听到的明暗、紧张或解决感，不用追求标准答案。"
    if strategy == "rule_coaching":
        return "能指出一个规则关键词，并用自己的话解释。"
    if strategy == "mindfulness":
        return "完成后能说出身体里一个明显感觉。"
    return "完成后能说出一个做到了的点和一个想调整的小点。"


def create_speed_reading_exercise(*, profile: dict[str, Any] | None = None, partner: dict[str, Any] | None = None) -> dict[str, Any]:
    del profile
    partner = partner or {}
    completed = len((partner.get("progress") or {}).get("completedMilestones", [])) if isinstance(partner.get("progress"), dict) else len(partner.get("progress") or [])
    seconds = 45 if completed <= 1 else 38 if completed <= 3 else 32
    text = pick([
        "学习新技能时，人很容易把别人的速度当成自己的标准。可是真正可靠的成长，常常来自很小但连续的练习。把任务拆小，把反馈放近，焦虑会慢慢变成可行动的线索。",
        "好的阅读不是抓住每一个字，而是迅速找到文章结构。先看主题，再找关键词，最后判断作者最想说明什么。读完后能答对关键问题，比机械读完更重要。",
    ])
    escaped = html.escape(text)
    card = f"""
    <div class="reading-card" data-reading-seconds="{seconds}">
      <div class="reading-head"><strong>速读小关卡 · {seconds} 秒</strong><span data-reading-countdown>3</span></div>
      <p class="reading-text is-hidden" data-reading-text>{escaped}</p>
      <div class="reading-actions">
        <button data-reading-action="start">开始</button>
        <button data-reading-action="pause">暂停</button>
        <button data-reading-action="restart">从头开始</button>
        <button data-reading-action="reveal">强制显示</button>
      </div>
      <div class="quiz-card">
        <strong>读完选一下</strong>
        <button data-jomo-choice="A">A. 成长主要靠比较别人</button>
        <button data-jomo-choice="B">B. 小任务和近反馈能降低焦虑</button>
        <button data-jomo-choice="C">C. 阅读必须记住每个字</button>
      </div>
    </div>
  """
    return {"seconds": seconds, "text": text, "html": card}


def choice_card_html() -> str:
    return """
    <div class="choice-card">
      <strong>今天的小路</strong>
      <button data-jomo-choice="我选轻松版">轻松版 · 5 分钟</button>
      <button data-jomo-choice="我选标准版">标准版 · 10 分钟</button>
    </div>
    """


def progress_action_reply(text: str, partner: dict[str, Any], skill: dict[str, Any]) -> dict[str, Any] | None:
    del partner, skill
    if re.search(r"跳过|skip", text, re.I):
        return {"text": "好，这关先轻轻跳过。不是逃跑，是给自己换一条能继续走的路。", "progress": {"action": "skipNext", "evidence": "跳过了一次小目标"}}
    if re.search(r"完成|结束.*小目标|结束.*目标", text):
        return {"text": "收到，这一关盖章。你不是靠猛冲赢的，是靠回来练这一下赢的。", "progress": {"action": "completeNext", "completeNext": True, "evidence": "完成了一个训练目标"}}
    if re.search(r"重置|reset|清理上文", text, re.I):
        return {"text": "我把这段上文收进小盒子里。我们从当前关卡重新开始，步子放轻一点。", "progress": {"action": "resetContext", "resetContext": True, "evidence": "重置了一次训练上下文"}}
    return None


def image_reply(skill: dict[str, Any]) -> str:
    if skill["strategy"] == "creative_review":
        return "我会按目标给这张练习先打 8 分：完成感不错。下一张只抓一个点，让线条慢一点点就好。"
    return "看到了这次练习证据。我先给 7 分，下一轮我们只调一个小地方，别一下子修太多。"


def count_reply(skill: dict[str, Any], count: str) -> str:
    if skill["strategy"] in {"movement_review", "mindfulness"}:
        return f"{count} 收到，今天的小能量已经落地。身体如果觉得累，我们就把质量放在数量前面。"
    return f"{count} 收到，是一颗很具体的小星星。我们继续按自己的节奏走。"


def infer_progress(*, text: str, attachment: Any, skill: dict[str, Any]) -> dict[str, Any] | None:
    if attachment:
        return {"evidence": f"上传了 {skill['name']} 练习图片，并收到一次 AI 反馈"}
    if count := extract_count(text):
        return {"evidence": f"完成 {count} {skill['name']} 练习", "completeNext": True}
    if re.search(r"^[ABCDabcd]$", text.strip()):
        return {"evidence": f"完成一次 {skill['name']} 选择题练习", "completeNext": text.strip().upper() == "B"}
    return None


def compact_context(partner: dict[str, Any], action: str, summary: str) -> dict[str, Any]:
    compacted = {
        "at": int(time.time() * 1000),
        "action": action,
        "summary": summary[:400],
        "progress": partner.get("progress") or {},
    }
    return compacted


def current_progress_summary(partner: dict[str, Any], skill: dict[str, Any]) -> str:
    progress = partner.get("progress") or {}
    completed = set(progress.get("completedMilestones", [])) if isinstance(progress, dict) else set(progress or [])
    skipped = set(progress.get("skippedMilestones", [])) if isinstance(progress, dict) else set()
    lines = []
    for node in flatten_nodes(skill):
        if node["type"] == "milestone":
            status = "完成" if node["id"] in completed else "跳过" if node["id"] in skipped else "进行中"
            lines.append(f"- {node['title']}：{status}；{node.get('description', '')}")
    return "\n".join(lines[:12]) or "暂无进度"


def wants_exercise(text: str) -> bool:
    value = text.strip()
    return len(value) <= 18 and bool(re.search(r"开始|速读|阅读|训练|练习|下一步|选项", value))


def wants_options(text: str) -> bool:
    return bool(re.search(r"下一步|选择|计划|怎么练|选项", text))


def wants_start_learning(text: str) -> bool:
    return bool(re.search(r"开始本关卡|开始这一关|开始今天学习|开始今天的学习|今日学习|开始学习", text))


def is_anxiety(text: str) -> bool:
    return bool(re.search(r"焦虑|落后|fomo|FOMO|着急|怕", text))


def extract_count(text: str) -> str:
    match = re.search(r"(\d+)\s*(个|次|组|秒|分钟)?", text)
    if not match:
        return ""
    return f"{match.group(1)}{match.group(2) or '次'}"


def tokens_for(text: str) -> list[dict[str, Any]]:
    return [{"type": "token", "data": {"text": chunk}, "delay": 24} for chunk in re.findall(r"[\s\S]{1,4}", text) or [text]]


def pick(items: list[str]) -> str:
    return random.choice(items)
