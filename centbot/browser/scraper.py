"""Allowed web data extraction (robots-aware, explicit allow-list)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.scraper")

DEFAULT_ALLOW = {
    "example.com",
    "www.example.com",
}


class AllowedScraper:
    def __init__(self, allow_hosts: set[str] | None = None, user_agent: str = "CENTBOT/1.0"):
        self.allow_hosts = allow_hosts or set(DEFAULT_ALLOW)
        self.user_agent = user_agent

    def is_allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        if host not in self.allow_hosts:
            return False
        robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
        rp = RobotFileParser()
        try:
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            # If robots cannot be read, deny by default for safety
            log.warning("robots.txt unreadable for %s; denying", host)
            return False

    def fetch_text(self, url: str, timeout: float = 15.0) -> dict[str, Any]:
        if not self.is_allowed(url):
            return {"ok": False, "error": "not_allowed", "url": url}
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": self.user_agent})
        resp.raise_for_status()
        return {"ok": True, "url": url, "status": resp.status_code, "text": resp.text[:200_000]}
