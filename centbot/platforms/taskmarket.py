"""TaskMarket connector."""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask


class TaskMarketConnector(PlatformConnector):
    name = "taskmarket"

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        if not self.api_key and not self.config.get("base_url"):
            return [
                PlatformTask(
                    platform=self.name,
                    external_id="tm-demo-text-1",
                    title="Summarize product feedback text",
                    description="Produce a concise summary and bullet list of themes.",
                    reward_amount=8.0,
                    reward_currency="EUR",
                    category_hint="text",
                    funded=True,
                    available=True,
                    automation_allowed=True,
                    payer_id="tm-payer",
                    payer_rating=0.75,
                    raw={"source": "demo"},
                ),
                PlatformTask(
                    platform=self.name,
                    external_id="tm-demo-lowpay-1",
                    title="Manual CAPTCHA farm (disallowed)",
                    description="Should be rejected by policy checks.",
                    reward_amount=0.1,
                    reward_currency="USD",
                    category_hint="other",
                    funded=False,
                    available=True,
                    automation_allowed=False,
                    payer_id="tm-unknown",
                    payer_rating=0.1,
                    raw={"source": "demo", "disallowed": True},
                ),
            ]
        return []

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Respect listing automation flags; skip automation_allowed=false.",
            "requires_human_review": True,
        }

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        if task.automation_allowed is False:
            return {"ok": False, "reason": "automation_not_allowed"}
        return {"ok": True, "external_id": task.external_id}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "submitted"}
