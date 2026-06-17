from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from .agent import ASSETS_DIR, has_ai_config, provider_info, safe_key, stream_agent_events
from .oss_storage import enabled as oss_enabled, upload_data_url
from .skills import find_skill, list_agent_skills, list_learning_skills, upsert_learning_skill
from .store import get_or_create_user, save_user_partners, update_profile
from .strategy import (
    create_chat_events,
    create_custom_skill_prompt,
    create_partner_plan,
    create_speed_reading_exercise,
    fallback_custom_skill,
    infer_progress,
    should_use_local_chat_strategy,
)


ROOT = Path(__file__).resolve().parents[2]


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "jomo-python-api", "version": "0.3.0", "ai": provider_info(), "oss": {"enabled": oss_enabled()}})


async def skills(_: Request) -> JSONResponse:
    return JSONResponse({"skills": list_learning_skills(), "agentSkills": list_agent_skills()})


async def login(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        user = get_or_create_user(str(body.get("username") or ""))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"user": user})


async def profile(request: Request) -> JSONResponse:
    body = await request.json()
    username = str(body.get("username") or "")
    try:
        user = update_profile(username, body.get("profile") or {})
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"user": user})


async def partner_plan(request: Request) -> JSONResponse:
    body = await request.json()
    skill = find_skill(list_learning_skills(), body.get("skillId"))
    if not skill:
        return JSONResponse({"error": "skill not found"}, status_code=404)
    return JSONResponse(create_partner_plan(profile=body.get("profile"), skill=skill))


async def speed_reading_exercise(request: Request) -> JSONResponse:
    body = await request.json()
    skill = find_skill(list_learning_skills(), body.get("skillId"))
    if not skill:
        return JSONResponse({"error": "skill not found"}, status_code=404)
    return JSONResponse(create_speed_reading_exercise(profile=body.get("profile"), partner=body.get("partner")))


async def custom_skill_prompt(request: Request) -> JSONResponse:
    body = await request.json()
    prompt = create_custom_skill_prompt(
        username=str(body.get("username") or "guest"),
        title=str(body.get("title") or "自定义技能"),
        target_level=str(body.get("targetLevel") or "入门"),
        tags=body.get("tags") or ["自定义"],
    )
    return JSONResponse({"prompt": prompt})


async def custom_skill(request: Request) -> JSONResponse:
    body = await request.json()
    title = str(body.get("title") or "自定义技能").strip()
    target_level = str(body.get("targetLevel") or "入门").strip()
    tags = [str(item).strip() for item in (body.get("tags") or ["自定义"]) if str(item).strip()]
    # Demo path: expose the exact prompt for the later agent, and create a usable local plan immediately.
    skill = fallback_custom_skill(title=title, target_level=target_level, tags=tags)
    skill["promptForAgent"] = create_custom_skill_prompt(
        username=str(body.get("username") or "guest"),
        title=title,
        target_level=target_level,
        tags=tags,
    )
    return JSONResponse({"skill": upsert_learning_skill(skill)})


async def admin_skill(request: Request) -> JSONResponse:
    body = await request.json()
    skill = find_skill(list_learning_skills(), body.get("skillId"))
    if not skill:
        return JSONResponse({"error": "skill not found"}, status_code=404)
    next_skill = body.get("skill")
    if not isinstance(next_skill, dict):
        return JSONResponse({"error": "invalid learning skill"}, status_code=400)
    if next_skill.get("id") != skill.get("id"):
        return JSONResponse({"error": "skill id cannot be changed"}, status_code=400)
    if not isinstance(next_skill.get("plan"), dict) or not isinstance(next_skill["plan"].get("goals"), list):
        return JSONResponse({"error": "invalid plan"}, status_code=400)
    return JSONResponse({"skill": upsert_learning_skill(next_skill)})


async def partners(request: Request) -> JSONResponse:
    username = request.path_params["username"]
    try:
        user = get_or_create_user(username)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    if request.method == "GET":
        return JSONResponse({"partners": user.get("partners") or []})
    body = await request.json()
    try:
        user = save_user_partners(username, body.get("partners") or [])
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"partners": user.get("partners") or []})


async def upload(request: Request) -> JSONResponse:
    body = await request.json()
    username = str(body.get("username") or "guest")
    data_url = str(body.get("dataUrl") or "")
    filename = str(body.get("filename") or "")
    media_type = str(body.get("mediaType") or "uploads")
    if not data_url:
        return JSONResponse({"error": "dataUrl is required"}, status_code=400)
    try:
        result = upload_data_url(data_url=data_url, filename=filename, username=username, kind=media_type)
    except Exception as error:
        return JSONResponse({"error": str(error)[:500], "oss": {"enabled": oss_enabled()}}, status_code=500)
    return JSONResponse({"upload": result})


async def chat(request: Request) -> Response:
    body = await request.json()
    skill = find_skill(list_learning_skills(), (body.get("partner") or {}).get("skillId"))
    if not skill:
        return JSONResponse({"error": "skill not found"}, status_code=404)

    use_agent = has_ai_config() and not should_use_local_chat_strategy(user_text=body.get("userText", ""), skill=skill)
    payload = {**body, "skill": skill}
    stream = stream_ai_response(payload) if use_agent else stream_local_events(local_chat_events(payload))
    return StreamingResponse(stream, media_type="text/event-stream; charset=utf-8", headers={"Cache-Control": "no-cache"})


async def asset(request: Request) -> Response:
    session = safe_key(request.path_params["session"])
    path = str(request.path_params["path"]).replace("\\", "/").strip("/")
    file_path = (ASSETS_DIR / session / path).resolve()
    root = (ASSETS_DIR / session).resolve()
    if root not in file_path.parents or not file_path.exists() or not file_path.is_file():
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(file_path)


async def stream_local_events(events: list[dict[str, Any]]) -> AsyncIterator[str]:
    for event in events:
        yield sse(event["type"], event.get("data") or {})
        if delay := event.get("delay"):
            await asyncio.sleep(float(delay) / 1000)
    yield sse("done", {"ok": True})


async def stream_ai_response(payload: dict[str, Any]) -> AsyncIterator[str]:
    body = {
        "profile": payload.get("profile") or {},
        "partner": payload.get("partner") or {},
        "userText": payload.get("userText") or "",
        "attachment": payload.get("attachment"),
        "skill": payload["skill"],
    }
    yield sse("agent.started", {
        "provider": "anthropic",
        "model": provider_info()["model"],
        "skill": payload["skill"]["name"],
        "strategy": payload["skill"]["strategy"],
        "sessionId": (body["partner"].get("sessionId") or body["partner"].get("id")),
    })
    try:
        async for event, data in stream_agent_events(body):
            yield sse(event, data)
        progress = infer_progress(text=body["userText"], attachment=body["attachment"], skill=payload["skill"])
        if progress:
            yield sse("progress", progress)
        yield sse("done", {"ok": True, "source": "ai"})
    except Exception as error:
        yield sse("agent.error", {"message": str(error)[:1200], "fallback": True})
        async for item in stream_local_events(local_chat_events(payload)):
            yield item


def local_chat_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return create_chat_events(
        profile=payload.get("profile") or {},
        partner=payload.get("partner") or {},
        user_text=payload.get("userText") or "",
        attachment=payload.get("attachment"),
        skill=payload["skill"],
    )


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def not_found(_: Request) -> PlainTextResponse:
    return PlainTextResponse("Not found", status_code=404)


load_dotenv()

app = Starlette(
    debug=True,
    routes=[
        Route("/api/health", health, methods=["GET"]),
        Route("/api/skills", skills, methods=["GET"]),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/profile", profile, methods=["POST"]),
        Route("/api/partners/plan", partner_plan, methods=["POST"]),
        Route("/api/speed-reading/exercise", speed_reading_exercise, methods=["POST"]),
        Route("/api/skills/custom/prompt", custom_skill_prompt, methods=["POST"]),
        Route("/api/skills/custom", custom_skill, methods=["POST"]),
        Route("/api/admin/skills", admin_skill, methods=["PUT"]),
        Route("/api/users/{username}/partners", partners, methods=["GET", "PUT"]),
        Route("/api/uploads", upload, methods=["POST"]),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/assets/{session}/{path:path}", asset, methods=["GET"]),
        Route("/{path:path}", not_found, methods=["GET"]),
    ],
)
