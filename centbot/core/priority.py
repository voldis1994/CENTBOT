"""Task priority scoring."""

from __future__ import annotations

from typing import Any


def score_priority(task: dict[str, Any]) -> int:
    """Higher is better. Scale ~0-100."""
    profit = float(task.get("expected_profit") or 0)
    prob = float(task.get("reward_probability") or 0)
    trust = float(task.get("payer_trust") or 0.5)
    hours = float(task.get("estimated_hours") or 1) or 1.0
    complexity = float(task.get("complexity") or 0.5)

    profit_per_hour = profit / hours
    score = (
        profit_per_hour * 25
        + prob * 30
        + trust * 20
        + max(0, 15 - complexity * 10)
        + (5 if task.get("funded") else 0)
    )
    return int(max(0, min(100, round(score))))


def sort_by_priority(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for t in tasks:
        item = dict(t)
        item["priority"] = score_priority(item)
        enriched.append(item)
    return sorted(enriched, key=lambda x: x["priority"], reverse=True)
