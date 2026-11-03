"""Browser automation module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.browser.playwright_mod import PlaywrightSession, playwright_available
from centbot.core.logger import get_logger

log = get_logger("centbot.browser")


class BrowserAutomation:
    def __init__(self, headless: bool = True, timeout_ms: int = 30000, user_agent: str | None = None):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent

    def run_scripted(self, steps: list[dict[str, Any]], evidence_dir: Path) -> dict[str, Any]:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        if not playwright_available():
            note = evidence_dir / "browser_skipped.txt"
            note.write_text("Playwright not installed. " + __import__("centbot.browser.playwright_mod", fromlist=["install_hint"]).install_hint())
            return {"ok": False, "error": "playwright_missing", "artifacts": [str(note)]}
        artifacts: list[str] = []
        with PlaywrightSession(self.headless, self.timeout_ms, self.user_agent) as session:
            for i, step in enumerate(steps):
                action = step.get("action")
                if action == "goto":
                    session.goto(step["url"])
                elif action == "click":
                    session.page.click(step["selector"])
                elif action == "fill":
                    session.page.fill(step["selector"], step.get("value", ""))
                elif action == "screenshot":
                    path = evidence_dir / f"step_{i}.png"
                    session.page.screenshot(path=str(path))
                    artifacts.append(str(path))
                elif action == "wait":
                    session.page.wait_for_timeout(int(step.get("ms", 500)))
                else:
                    log.warning("Unknown browser action: %s", action)
            final = evidence_dir / "final.png"
            session.page.screenshot(path=str(final))
            artifacts.append(str(final))
        return {"ok": True, "artifacts": artifacts}
