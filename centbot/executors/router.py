"""Route tasks to the correct executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor
from centbot.executors.csv_proc import CSVProcessor
from centbot.executors.excel_proc import ExcelProcessor
from centbot.executors.image_proc import ImageProcessor
from centbot.executors.json_xml_proc import JsonXmlProcessor
from centbot.executors.pdf_proc import PDFProcessor
from centbot.executors.programming import ProgrammingExecutor
from centbot.executors.text_proc import TextProcessor
from centbot.executors.testing import validate_artifacts, write_test_report


class TaskExecutorRouter:
    def __init__(self) -> None:
        self.executors: list[Executor] = [
            CSVProcessor(),
            ExcelProcessor(),
            JsonXmlProcessor(),
            PDFProcessor(),
            ImageProcessor(),
            TextProcessor(),
            ProgrammingExecutor(),
        ]

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        category = task.get("category") or "other"
        for ex in self.executors:
            if ex.can_handle(category):
                result = ex.execute(task, workdir)
                checks = validate_artifacts(result.to_dict())
                write_test_report(workdir, checks)
                if not checks["ok"] and result.ok:
                    result.ok = False
                    result.error = f"artifact_validation_failed:{checks['missing_artifacts']}"
                return result
        # Fallback: write a stub completion note
        workdir.mkdir(parents=True, exist_ok=True)
        note = workdir / "manual_required.txt"
        note.write_text(f"No specialized executor for category={category}\n{task.get('title')}\n", encoding="utf-8")
        return ExecutionResult(ok=False, category=category, error="unsupported_category", artifacts=[str(note)])
