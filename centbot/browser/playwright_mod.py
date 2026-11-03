"""Playwright integration."""

from __future__ import annotations

from typing import Any

from centbot.core.logger import get_logger

log = get_logger("centbot.browser.playwright")


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def install_hint() -> str:
    return "pip install playwright && playwright install chromium"


class PlaywrightSession:
    def __init__(self, headless: bool = True, timeout_ms: int = 30000, user_agent: str | None = None):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "PlaywrightSession":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        context = self._browser.new_context(user_agent=self.user_agent) if self.user_agent else self._browser.new_context()
        self._page = context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *args: Any) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("Playwright session not started")
        return self._page

    def goto(self, url: str) -> str:
        self.page.goto(url)
        return self.page.title()
