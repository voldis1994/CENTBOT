"""Task analysis pipeline: availability, funding, trust, category, complexity, estimates, profit, reject/accept."""

from __future__ import annotations

import re
from typing import Any

from centbot.core.logger import ActionJournal, get_logger
from centbot.core.priority import score_priority
from centbot.platforms.base import PlatformTask

log = get_logger("centbot.analysis")

CATEGORY_KEYWORDS = {
    "csv": ["csv", "spreadsheet clean", "delimiter"],
    "excel": ["excel", "xlsx", "workbook", "sheet"],
    "json_xml": ["json", "xml", "transform"],
    "pdf": ["pdf", "invoice", "extract text"],
    "image": ["image", "png", "jpg", "screenshot", "vision"],
    "text": ["summarize", "text", "copywriting", "rewrite"],
    "programming": ["python", "function", "code", "unit-test", "implement"],
    "browser": ["browser", "web", "scrape", "playwright"],
    "android": ["android", "apk", "emulator", "adb"],
}


def categorize(title: str, description: str, hint: str = "") -> str:
    if hint and hint in CATEGORY_KEYWORDS:
        return hint
    blob = f"{title} {description} {hint}".lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in blob for w in words):
            return cat
    return "other"


def complexity_score(title: str, description: str, category: str) -> float:
    length = len(description or "")
    base = {
        "csv": 0.3,
        "excel": 0.4,
        "json_xml": 0.35,
        "pdf": 0.45,
        "image": 0.5,
        "text": 0.35,
        "programming": 0.65,
        "browser": 0.7,
        "android": 0.8,
        "other": 0.55,
    }.get(category, 0.5)
    bump = min(0.3, length / 2000)
    if re.search(r"multi[- ]?step|complex|urgent", f"{title} {description}", re.I):
        bump += 0.1
    return round(min(1.0, base + bump), 3)


def estimate_hours(complexity: float, category: str) -> float:
    base_hours = {
        "csv": 0.4,
        "excel": 0.6,
        "json_xml": 0.5,
        "pdf": 0.5,
        "image": 0.7,
        "text": 0.4,
        "programming": 1.5,
        "browser": 1.2,
        "android": 2.0,
        "other": 1.0,
    }.get(category, 1.0)
    return round(base_hours * (0.7 + complexity), 2)


def estimate_cost(hours: float, cpu_rate_per_hour: float = 0.15) -> float:
    """Rough electricity/compute cost estimate."""
    return round(hours * cpu_rate_per_hour, 4)


def reward_probability(task: dict[str, Any]) -> float:
    trust = float(task.get("payer_trust") or 0.5)
    funded = 1.0 if task.get("funded") else 0.25
    available = 1.0 if task.get("available") else 0.0
    auto = task.get("automation_allowed")
    auto_factor = 1.0 if auto is not False else 0.1
    return round(max(0.0, min(1.0, 0.35 * trust + 0.35 * funded + 0.2 * available + 0.1 * auto_factor)), 3)


def expected_profit(reward: float, cost: float, probability: float) -> float:
    return round(reward * probability - cost, 4)


class AnalysisPipeline:
    def __init__(self, config: dict[str, Any], journal: ActionJournal):
        self.config = config
        self.journal = journal

    def analyze(self, row: dict[str, Any]) -> dict[str, Any]:
        task: PlatformTask | None = row.get("_task")
        title = row.get("title") or (task.title if task else "")
        description = row.get("description") or (task.description if task else "")
        hint = (task.category_hint if task else "") or row.get("category") or ""

        # Availability & funding & automation
        available = bool(row.get("available", 1))
        if task is not None:
            available = available and bool(task.available)
        funded = bool(row.get("funded", 0))
        automation_ok = row.get("automation_allowed")
        if automation_ok is None and task is not None:
            automation_ok = task.automation_allowed

        category = categorize(title, description, hint)
        complexity = complexity_score(title, description, category)
        hours = estimate_hours(complexity, category)
        cost = estimate_cost(hours)
        row["category"] = category
        row["complexity"] = complexity
        row["estimated_hours"] = hours
        row["estimated_cost"] = cost
        row["available"] = 1 if available else 0
        row["funded"] = 1 if funded else 0
        row["reward_probability"] = reward_probability(row)
        reward = float(row.get("reward_amount") or 0)
        row["expected_profit"] = expected_profit(reward, cost, row["reward_probability"])
        row["priority"] = score_priority(row)

        decision = self.decide(row, automation_ok)
        row["status"] = decision["status"]
        row["reject_reason"] = decision.get("reason")
        return row

    def decide(self, row: dict[str, Any], automation_ok: bool | None) -> dict[str, Any]:
        min_profit = float(self.config.get("min_expected_profit", 0.5))
        min_prob = float(self.config.get("min_reward_probability", 0.4))
        max_hours = float(self.config.get("max_estimated_hours", 8))
        min_trust = float(self.config.get("reject_untrusted_payer_below", 0.3))

        if automation_ok is False:
            return {"status": "rejected", "reason": "automation_not_allowed"}
        if not row.get("available"):
            return {"status": "rejected", "reason": "unavailable"}
        if self.config.get("reject_unfunded", True) and not row.get("funded"):
            return {"status": "rejected", "reason": "unfunded"}
        if float(row.get("payer_trust") or 0) < min_trust:
            return {"status": "rejected", "reason": "low_payer_trust"}
        if float(row.get("estimated_hours") or 0) > max_hours:
            return {"status": "rejected", "reason": "too_long"}
        if float(row.get("reward_probability") or 0) < min_prob:
            return {"status": "rejected", "reason": "low_reward_probability"}
        if float(row.get("expected_profit") or 0) < min_profit:
            return {"status": "rejected", "reason": "unprofitable"}
        return {"status": "eligible", "reason": None}


class AutoAcceptor:
    def __init__(self, platforms: dict, config: dict[str, Any], journal: ActionJournal, dry_run: bool = True):
        self.platforms = platforms
        self.config = config
        self.journal = journal
        self.dry_run = dry_run

    def accept(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") != "eligible":
            return {"ok": False, "reason": "not_eligible"}
        if not self.config.get("auto_accept", False) and not self.dry_run:
            return {"ok": False, "reason": "auto_accept_disabled"}
        platform = row["platform"]
        conn = self.platforms.get(platform)
        if not conn:
            return {"ok": False, "reason": "unknown_platform"}
        task = row.get("_task")
        if self.dry_run:
            self.journal.record("accept", "dry_run", task_id=row["id"], platform=platform)
            return {"ok": True, "mode": "dry_run", "task_id": row["id"]}
        assert task is not None
        result = conn.accept_task(task)
        self.journal.record("accept", "ok" if result.get("ok") else "error", task_id=row["id"], result=result)
        return result
