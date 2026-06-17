from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / ".run" / "jomo-data"
DB_PATH = DATA_DIR / "store.json"
USERNAME_RE = re.compile(r"^[A-Za-z0-9]{1,30}$")


def now_ms() -> int:
    return int(time.time() * 1000)


def load_db() -> dict[str, Any]:
    if not DB_PATH.exists():
        db = {"users": {}}
        save_db(db)
        return db
    try:
        db = json.loads(DB_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        db = {"users": {}}
    if not isinstance(db.get("users"), dict):
        db["users"] = {}
    return db


def save_db(db: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), "utf-8")


def get_or_create_user(username: str) -> dict[str, Any]:
    value = str(username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("username must be 1-30 letters or numbers")
    db = load_db()
    user = db["users"].get(value)
    if not user:
        user = {
            "username": value,
            "createdAt": now_ms(),
            "profile": {"username": value, "displayName": value, "goal": "每天轻松练一点"},
            "partners": [],
        }
        db["users"][value] = user
        save_db(db)
    user.setdefault("partners", [])
    user.setdefault("profile", {"username": value, "displayName": value, "goal": "每天轻松练一点"})
    return user


def update_profile(username: str, profile: dict[str, Any]) -> dict[str, Any]:
    db = load_db()
    user = get_or_create_user(username)
    profile = {
        "username": username,
        "displayName": str(profile.get("displayName") or username).strip()[:30],
        "goal": str(profile.get("goal") or "每天轻松练一点").strip()[:80],
    }
    user["profile"] = profile
    user["updatedAt"] = now_ms()
    db = load_db()
    db["users"][username] = user
    save_db(db)
    return user


def save_user_partners(username: str, partners: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(partners, list):
        raise ValueError("partners must be a list")
    user = get_or_create_user(username)
    cleaned = [clean_partner(item) for item in partners if isinstance(item, dict)]
    user["partners"] = cleaned
    user["updatedAt"] = now_ms()
    db = load_db()
    db["users"][username] = user
    save_db(db)
    return user


def clean_partner(partner: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "sessionId", "name", "skillId", "plan", "progress", "evidence",
        "compacts", "messages", "createdAt", "updatedAt",
    }
    cleaned = {key: partner.get(key) for key in allowed if key in partner}
    cleaned.setdefault("messages", [])
    cleaned.setdefault("evidence", [])
    cleaned.setdefault("compacts", [])
    cleaned["updatedAt"] = now_ms()
    return cleaned
