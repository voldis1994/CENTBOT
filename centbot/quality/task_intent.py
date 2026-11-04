"""Distinguish missing input files from tasks that ask to create new outputs."""

from __future__ import annotations

import re
from typing import Any


_CREATE_VERBS = (
    r"create",
    r"generate",
    r"make",
    r"build",
    r"produce",
    r"draw",
    r"render",
    r"compose",
    r"design",
    r"write",
    r"izveido",
    r"ģenerē",
    r"sagatavo",
)
_INPUT_HINTS = (
    r"given",
    r"using the attached",
    r"from the input",
    r"process the",
    r"convert",
    r"transform",
    r"attached file",
    r"provided file",
    r"input\.",
)


def task_blob(task: dict[str, Any]) -> str:
    return f"{task.get('title') or ''}\n{task.get('description') or ''}"


def is_create_output_task(task: dict[str, Any], *, extensions: tuple[str, ...] = ()) -> bool:
    """True when the brief asks to produce a new file rather than process an uploaded input."""
    blob = task_blob(task).lower()
    if any(re.search(rf"\b{v}\b", blob) for v in _CREATE_VERBS):
        if any(re.search(h, blob) for h in _INPUT_HINTS):
            # Explicit transform of provided input
            return False
        return True
    if extensions and any(ext.lstrip(".").lower() in blob for ext in extensions):
        # Mentions extension + create-ish phrasing already handled; alone is not enough
        return False
    # Planner signal
    plan = task.get("_execution_plan") or {}
    if str(plan.get("create_vs_transform") or "").lower() == "create":
        return True
    analysis = (plan.get("analysis") or {}) if isinstance(plan, dict) else {}
    if str(analysis.get("create_vs_transform") or "").lower() == "create":
        return True
    return False


def missing_input_error(names: list[str], *, create_allowed: bool = False) -> str:
    joined = "|".join(names)
    if create_allowed:
        return f"missing_input_or_create:{joined}"
    return f"missing_input:{joined}"
