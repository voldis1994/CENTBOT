"""Text processing — uses task description / input.txt (real brief, not synthetic filler)."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor
from centbot.quality.deliverables import ensure_named_deliverables, named_deliverables
from centbot.quality.task_intent import is_create_output_task


class TextProcessor(Executor):
    category = "text"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        src = workdir / "input.txt"
        text = ""
        if src.exists():
            text = src.read_text(encoding="utf-8")
        else:
            text = str(task.get("description") or "").strip()
        title = str(task.get("title") or "").strip()
        create = is_create_output_task(task, extensions=(".md", ".txt"))
        if not text and not (create and title):
            return ExecutionResult(ok=False, category=self.category, error="missing_input:description|input.txt")
        if not text:
            text = title
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        words = re.findall(r"[A-Za-zāčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ']+", text.lower())
        common = Counter(words).most_common(8)
        summary = {
            "sentence_count": len(sentences),
            "word_count": len(words),
            "top_words": common,
            "short_summary": ". ".join(sentences[:2]) + ("." if sentences else ""),
        }
        out = workdir / "summary.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts = [str(out)]
        # Named markdown/text deliverables (faq.md, notes.txt, …)
        if create or any(Path(n).suffix.lower() in {".md", ".txt"} for n in named_deliverables(task)):
            ensured = ensure_named_deliverables(task, workdir, {"artifacts": artifacts, "ok": True})
            artifacts = list(ensured.get("artifacts") or artifacts)
            summary["named_files"] = ensured.get("created") or []
        return ExecutionResult(ok=True, category=self.category, output=summary, artifacts=artifacts)
