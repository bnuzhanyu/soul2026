from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LEARNING_SKILLS_DIR = ROOT / "backend" / "learning_skills"
AGENT_SKILLS_DIR = ROOT / "backend" / "agent_skills"


def list_learning_skills() -> list[dict[str, Any]]:
    LEARNING_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for skill_dir in sorted(path for path in LEARNING_SKILLS_DIR.iterdir() if path.is_dir()):
        skill_path = skill_dir / "skill.json"
        if not skill_path.exists():
            continue
        try:
            skill = json.loads(skill_path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(skill, dict) or not skill.get("id") or not skill.get("name"):
            continue
        skill.setdefault("tags", [])
        skill.setdefault("agentSkills", [])
        skill["_path"] = str(skill_path)
        items.append(skill)
    return deepcopy(items)


def list_agent_skills() -> list[dict[str, Any]]:
    AGENT_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skills = []
    for skill_dir in sorted(path for path in AGENT_SKILLS_DIR.iterdir() if path.is_dir()):
        readme = skill_dir / "SKILL.md"
        skills.append({
            "id": skill_dir.name,
            "name": skill_dir.name,
            "enabled": readme.exists(),
            "path": str(skill_dir),
        })
    return skills


def upsert_learning_skill(skill: dict[str, Any]) -> dict[str, Any]:
    skill = deepcopy(skill)
    skill_id = safe_id(str(skill.get("id") or skill.get("name") or f"custom-{int(time.time())}"))
    skill["id"] = skill_id
    skill.pop("_path", None)
    skill.setdefault("tags", [])
    skill.setdefault("agentSkills", [])
    skill["updatedAt"] = now_ms()
    skill_dir = LEARNING_SKILLS_DIR / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "skill.json"
    if not path.exists():
        skill.setdefault("createdAt", now_ms())
    path.write_text(json.dumps(skill, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return skill


def find_skill(skills: list[dict[str, Any]], skill_id: str | None) -> dict[str, Any] | None:
    for skill in skills:
        if skill.get("id") == skill_id:
            return skill
    return None


def flatten_nodes(skill: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for goal in (skill.get("plan") or {}).get("goals", []):
        nodes.append({**goal, "type": "goal", "goalId": goal["id"]})
        for milestone in goal.get("milestones", []):
            nodes.append({**milestone, "type": "milestone", "goalId": goal["id"]})
    return nodes


def safe_id(value: str) -> str:
    value = value.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:48]
    return cleaned or f"custom-{int(time.time())}"


def now_ms() -> int:
    return int(time.time() * 1000)
