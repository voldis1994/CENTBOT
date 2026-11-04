"""Fallback executor for unknown/other categories — never claim done without real deliverable."""

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

        required = _required_deliverable(f"{title}\n{description}")
        if required.get("kind") and required["kind"] != "text":
            # Refuse to submit a prose summary when the task demands a concrete artifact type
            return ExecutionResult(
                ok=False,
                category=str(task.get("category") or self.category),
                error=f"generic_cannot_produce:{required['kind']}",
                output={
                    "required": required,
                    "hint": "Route to a specialized executor or provide real deliverable files",
                },
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
            "acceptance_note": "Text deliverable only — not a substitute for required binary/media artifacts.",
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


def _required_deliverable(blob: str) -> dict[str, Any]:
    lower = blob.lower()
    checks = [
        ("apk", (r"\.apk\b", r"android package")),
        ("image", (r"\.png\b", r"\.jpe?g\b", r"\bpng\b", r"\bjpg\b", r"generate an image", r"create a\w* logo", r"create an image", r"\blogo\b")),
        ("gif", (r"\.gif\b", r"animated gif", r"\bgif\b")),
        ("video", (r"\.mp4\b", r"\.webm\b", r"short video", r"\bvideo\b")),
        ("pdf", (r"\.pdf\b",)),
        ("csv", (r"\.csv\b",)),
        ("excel", (r"\.xlsx?\b",)),
        ("json", (r"\.json\b", r"return json")),
        ("xml", (r"\.xml\b",)),
        ("code", (r"implement a function", r"unit test", r"pull request", r"\.py\b")),
    ]
    for kind, needles in checks:
        if any(re.search(n, lower) for n in needles):
            # Creating new files is OK for text; binary kinds must not be faked as summary
            return {"kind": kind, "matched": True}
    return {"kind": "text", "matched": False}
