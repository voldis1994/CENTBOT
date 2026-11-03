"""Text processing module."""

from __future__ import annotations

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
        if not src.exists():
            body = task.get("description") or "Great product. Shipping was slow. Support was helpful. Great value."
            src.write_text(body, encoding="utf-8")
        text = src.read_text(encoding="utf-8")
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
        import json

        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return ExecutionResult(ok=True, category=self.category, output=summary, artifacts=[str(out)])
