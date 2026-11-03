"""Excel processing module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


class ExcelProcessor(Executor):
    category = "excel"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            import pandas as pd
        except ImportError as exc:
            return ExecutionResult(ok=False, category=self.category, error=f"pandas missing: {exc}")

        src = workdir / "input.xlsx"
        if not src.exists():
            demo = pd.DataFrame({"month": ["Jan", "Feb"], "sales": [10, 20]})
            demo.to_excel(src, index=False)
        df = pd.read_excel(src)
        summary = pd.DataFrame({"total_sales": [df.select_dtypes("number").sum().sum()], "rows": [len(df)]})
        out = workdir / "summary.xlsx"
        summary.to_excel(out, index=False)
        return ExecutionResult(ok=True, category=self.category, output=summary.to_dict(), artifacts=[str(out)])
