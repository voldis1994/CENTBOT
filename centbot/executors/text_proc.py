"""Text processing — uses task description / input.txt (real brief, not synthetic filler)."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


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
        if not text:
            return ExecutionResult(ok=False, category=self.category, error="missing_input:description|input.txt")
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
        return ExecutionResult(ok=True, category=self.category, output=summary, artifacts=[str(out)])
