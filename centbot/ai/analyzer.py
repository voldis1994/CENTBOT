"""AI task analyzer — full brief understanding (goal, conditions, files, acceptance)."""

from __future__ import annotations

import json
import re
from typing import Any

from centbot.ai.ollama_client import OllamaClient

_FILE_PATTERNS = [
    (r"\b[\w./-]+\.(png|jpe?g|gif|webp|mp4|webm|mov)\b", "media"),
    (r"\b[\w./-]+\.(csv|xlsx?|xls)\b", "tabular"),
    (r"\b[\w./-]+\.(json|xml|ya?ml)\b", "structured"),
    (r"\b[\w./-]+\.(pdf|txt|md)\b", "document"),
    (r"\b[\w./-]+\.(apk|aab)\b", "android"),
    (r"\b[\w./-]+\.(py|js|ts|java|kt)\b", "code"),
]


class AITaskAnalyzer:
    def __init__(self, client: OllamaClient, enabled: bool = True):
        self.client = client
        self.enabled = enabled

    def analyze(self, task: dict[str, Any]) -> dict[str, Any]:
        base = self._heuristic(task)
        if not self.enabled:
            return base
        prompt = (
            "Analyze this paid task. Reply with JSON keys: "
            "goal, conditions, required_files, acceptance_criteria, risks, steps, skills, create_vs_transform.\n"
            f"Title: {task.get('title')}\n"
            f"Description: {task.get('description')}\n"
            f"Category hint: {task.get('category')}\n"
            f"Reward: {task.get('reward_amount')} {task.get('reward_currency')}\n"
        )
        result = self.client.generate(prompt)
        if not result.get("ok"):
            return {**base, "ai_error": result.get("error")}
        parsed = _try_parse_json(result.get("response") or "")
        merged = {**base, "ok": True, "mode": "ollama", "response": result.get("response")}
        if parsed:
            for key in (
                "goal",
                "conditions",
                "required_files",
                "acceptance_criteria",
                "risks",
                "steps",
                "skills",
                "create_vs_transform",
            ):
                if key in parsed and parsed[key] not in (None, "", []):
                    merged[key] = parsed[key]
        return merged

    def _heuristic(self, task: dict[str, Any]) -> dict[str, Any]:
        title = str(task.get("title") or "")
        description = str(task.get("description") or "")
        blob = f"{title}\n{description}".strip()
        files = _extract_files(blob)
        create = _looks_like_create(blob)
        goal = _first_sentence(description) or title or "Complete the paid task"
        conditions = _extract_conditions(blob)
        acceptance = _extract_acceptance(blob)
        category = task.get("category") or "general"
        steps = [
            "understand_requirements",
            "gather_inputs" if not create else "create_deliverable",
            "execute",
            "verify_acceptance",
            "submit",
        ]
        return {
            "ok": True,
            "mode": "heuristic",
            "goal": goal,
            "conditions": conditions,
            "required_files": files,
            "acceptance_criteria": acceptance,
            "create_vs_transform": "create" if create else "transform",
            "risks": [] if task.get("funded") else ["unfunded"],
            "steps": steps,
            "skills": [category],
        }


def _try_parse_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _extract_files(blob: str) -> list[str]:
    found: list[str] = []
    for pat, _kind in _FILE_PATTERNS:
        for m in re.finditer(pat, blob, re.I):
            name = m.group(0)
            if name not in found:
                found.append(name)
    return found


def _looks_like_create(blob: str) -> bool:
    lower = blob.lower()
    create_verbs = (
        "create",
        "generate",
        "make",
        "build",
        "produce",
        "draw",
        "render",
        "compose",
        "write a",
        "design",
        "izveido",
        "ģenerē",
        "sagatavo",
    )
    transform_verbs = ("given", "using the attached", "from the input", "process the", "convert", "transform")
    if any(v in lower for v in transform_verbs):
        return False
    return any(v in lower for v in create_verbs)


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return (parts[0] if parts else "").strip()[:300]


def _extract_conditions(blob: str) -> list[str]:
    out: list[str] = []
    for line in blob.splitlines():
        s = line.strip()
        if re.match(r"^[-*•]\s+", s) or re.match(r"^\d+[.)]\s+", s):
            out.append(re.sub(r"^[-*•\d.)\s]+", "", s)[:240])
        elif re.search(r"\bmust\b|\bshould\b|\brequired\b|\bnosacīj|\bjābūt\b", s, re.I):
            out.append(s[:240])
    return out[:12]


def _extract_acceptance(blob: str) -> list[str]:
    out: list[str] = []
    capture = False
    for line in blob.splitlines():
        if re.search(r"acceptance|done when|definition of done|pieņemšan|kritērij", line, re.I):
            capture = True
            continue
        if capture:
            s = line.strip()
            if not s:
                if out:
                    break
                continue
            out.append(s[:240])
    if not out:
        for line in blob.splitlines():
            if re.search(r"\bdeliver\b|\boutput\b|\bresult\b|\bresultāt", line, re.I):
                out.append(line.strip()[:240])
    return out[:10]
