"""CSV processing module — requires real input.csv (no demo generation)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


class CSVProcessor(Executor):
    category = "csv"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        src = workdir / "input.csv"
        if not src.exists():
            return ExecutionResult(ok=False, category=self.category, error="missing_input:input.csv")
        rows: list[dict[str, str]] = []
        with open(src, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            seen = set()
            for row in reader:
                cleaned = {k: (v or "").strip() for k, v in row.items()}
                if "email" in cleaned:
                    cleaned["email"] = cleaned["email"].lower()
                key = tuple(cleaned.get(f, "") for f in fieldnames)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(cleaned)
        out = workdir / "output.csv"
        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames or ["email", "name"])
            writer.writeheader()
            writer.writerows(rows)
        return ExecutionResult(ok=True, category=self.category, output={"rows": len(rows)}, artifacts=[str(out)])
