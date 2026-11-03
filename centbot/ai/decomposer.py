"""Split tasks into subtasks."""

from __future__ import annotations

from typing import Any


def decompose(task: dict[str, Any]) -> list[dict[str, Any]]:
    category = task.get("category") or "other"
    base = [
        {"name": "prepare_workspace", "worker": "system"},
        {"name": "execute_main", "worker": category},
        {"name": "verify_output", "worker": "quality"},
        {"name": "package_evidence", "worker": "quality"},
    ]
    if category in {"browser", "android"}:
        base.insert(1, {"name": "bootstrap_runtime", "worker": category})
    if category == "programming":
        base.insert(2, {"name": "run_unit_tests", "worker": "testing"})
    return [{"task_id": task.get("id"), **s} for s in base]
