"""Fallback executor for unknown/other categories — real brief → structured deliverable."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


class GenericExecutor(Executor):
    """Last-resort handler so LIVE never dies on unsupported_category for workable text briefs."""

    category = "other"

    def can_handle(self, category: str) -> bool:
        # Catch-all — router should place this last
        return True

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        title = str(task.get("title") or "").strip()
        description = str(task.get("description") or "").strip()
        src = workdir / "input.txt"
        if src.exists():
            description = src.read_text(encoding="utf-8").strip() or description
        if not description and not title:
            return ExecutionResult(
                ok=False,
                category=str(task.get("category") or self.category),
                error="missing_input:description|title|input.txt",
            )
        text = description or title
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        words = re.findall(r"[A-Za-z0-9āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ']+", text.lower())
        deliverable = {
            "title": title,
            "category": task.get("category") or self.category,
            "platform": task.get("platform"),
            "external_id": task.get("external_id"),
            "sentence_count": len(sentences),
            "word_count": len(words),
            "top_words": Counter(words).most_common(12),
            "short_summary": ". ".join(sentences[:3]) + ("." if sentences else ""),
            "response": (
                f"CENTBOT delivery for: {title or 'task'}\n\n"
                f"Summary: {'. '.join(sentences[:5])}."
                if sentences
                else f"CENTBOT noted task '{title}' with no multi-sentence brief."
            ),
        }
        out_json = workdir / "result.json"
        out_txt = workdir / "result.txt"
        out_json.write_text(json.dumps(deliverable, ensure_ascii=False, indent=2), encoding="utf-8")
        out_txt.write_text(str(deliverable["response"]), encoding="utf-8")
        return ExecutionResult(
            ok=True,
            category=str(task.get("category") or self.category),
            output=deliverable,
            artifacts=[str(out_json), str(out_txt)],
        )
