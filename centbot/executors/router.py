"""Route tasks to the correct executor, including browser and Android."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.android_exec import AndroidExecutor
from centbot.executors.base import ExecutionResult, Executor
from centbot.executors.browser_exec import BrowserExecutor
from centbot.executors.csv_proc import CSVProcessor
from centbot.executors.excel_proc import ExcelProcessor
from centbot.executors.generic import GenericExecutor
from centbot.executors.image_proc import ImageProcessor
from centbot.executors.json_xml_proc import JsonXmlProcessor
from centbot.executors.pdf_proc import PDFProcessor
from centbot.executors.programming import ProgrammingExecutor
from centbot.executors.text_proc import TextProcessor
from centbot.executors.testing import validate_artifacts, write_test_report


class TaskExecutorRouter:
    def __init__(
        self,
        *,
        browser_enabled: bool = True,
        android_enabled: bool = False,
        headless: bool = True,
        timeout_ms: int = 30000,
        user_agent: str | None = None,
        adb_path: str = "adb",
        emulator_path: str = "emulator",
    ) -> None:
        self.executors: list[Executor] = [
            CSVProcessor(),
            ExcelProcessor(),
            JsonXmlProcessor(),
            PDFProcessor(),
            ImageProcessor(),
            TextProcessor(),
            ProgrammingExecutor(),
            BrowserExecutor(headless=headless, timeout_ms=timeout_ms, user_agent=user_agent),
            AndroidExecutor(adb_path=adb_path, emulator_path=emulator_path, enabled=android_enabled),
            # Catch-all LAST — TaskMarket/BasedAgents often land as category=other
            GenericExecutor(),
        ]
        if not browser_enabled:
            self.executors = [e for e in self.executors if e.category != "browser"]

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        category = task.get("category") or "other"
        for ex in self.executors:
            if not ex.can_handle(category):
                continue
            result = ex.execute(task, workdir)
            # Browser tasks without scripted steps → fall back to generic text delivery
            if (
                not result.ok
                and ex.category == "browser"
                and str(result.error or "").startswith("missing_input:browser_steps")
            ):
                continue
            checks = validate_artifacts(result.to_dict())
            write_test_report(workdir, checks)
            if not checks["ok"] and result.ok:
                result.ok = False
                result.error = f"artifact_validation_failed:{checks['missing_artifacts']}"
            return result
        workdir.mkdir(parents=True, exist_ok=True)
        note = workdir / "unsupported_category.txt"
        note.write_text(f"No executor for category={category}\n{task.get('title')}\n", encoding="utf-8")
        return ExecutionResult(ok=False, category=category, error="unsupported_category", artifacts=[str(note)])
