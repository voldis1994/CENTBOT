"""Jobbi work catalog connector."""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask


class JobbiConnector(PlatformConnector):
    name = "jobbi"

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        # Demo catalog when API is not configured — used for dry-run / integration checks.
        if not self.api_key and not self.config.get("base_url"):
            return [
                PlatformTask(
                    platform=self.name,
                    external_id="jobbi-demo-csv-1",
                    title="Clean and normalize CSV customer list",
                    description="Remove duplicates, normalize emails, output cleaned CSV.",
                    reward_amount=12.0,
                    reward_currency="USD",
                    category_hint="csv",
                    funded=True,
                    available=True,
                    automation_allowed=True,
                    payer_id="jobbi-demo-payer",
                    payer_rating=0.9,
                    raw={"source": "demo"},
                )
            ]
        # Live API path (placeholder for real credentials)
        return self._fetch_remote()

    def _fetch_remote(self) -> list[PlatformTask]:
        # Intentionally conservative: require explicit base_url + key; no scraping.
        return []

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Use official API only. Demo mode for dry_run.",
            "requires_human_review": False,
        }

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        return {"ok": True, "platform": self.name, "external_id": task.external_id, "mode": "demo"}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "platform": self.name, "external_id": task.external_id, "status": "submitted", "payload_keys": list(payload)}
