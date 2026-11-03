"""Executor base types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecutionResult:
    ok: bool
    category: str
    output: Any = None
    artifacts: list[str] = field(default_factory=list)
    error: str | None = None
    evidence_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "category": self.category,
            "output": self.output,
            "artifacts": self.artifacts,
            "error": self.error,
            "evidence_dir": self.evidence_dir,
        }


class Executor:
    category = "other"

    def can_handle(self, category: str) -> bool:
        return category == self.category

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        raise NotImplementedError
