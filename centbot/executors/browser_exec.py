"""Browser automation executor wired to Playwright module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.browser.automation import BrowserAutomation
from centbot.executors.base import ExecutionResult, Executor


class BrowserExecutor(Executor):
    category = "browser"

    def __init__(self, headless: bool = True, timeout_ms: int = 30000, user_agent: str | None = None):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        evidence = workdir / "browser"
        steps = task.get("browser_steps")
        if not steps:
            # Derive a minimal allowed navigation from explicit steps file
            steps_path = workdir / "browser_steps.json"
            if steps_path.exists():
                import json

                steps = json.loads(steps_path.read_text(encoding="utf-8"))
            else:
                return ExecutionResult(
                    ok=False,
                    category=self.category,
                    error="missing_input:browser_steps|browser_steps.json",
                )
        automation = BrowserAutomation(self.headless, self.timeout_ms, self.user_agent)
        result = automation.run_scripted(steps, evidence)
        return ExecutionResult(
            ok=bool(result.get("ok")),
            category=self.category,
            output=result,
            artifacts=result.get("artifacts") or [],
            error=result.get("error"),
            evidence_dir=str(evidence),
        )
