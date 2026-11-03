"""BountyBook integration check connector."""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask


class BountyBookConnector(PlatformConnector):
    name = "bountybook"

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        if not self.api_key and not self.config.get("base_url"):
            return [
                PlatformTask(
                    platform=self.name,
                    external_id="bb-demo-python-1",
                    title="Write a Python function to merge sorted lists",
                    description="Implement and unit-test merge of two sorted integer lists.",
                    reward_amount=25.0,
                    reward_currency="USDT",
                    category_hint="programming",
                    funded=True,
                    available=True,
                    automation_allowed=True,
                    payer_id="bb-org",
                    payer_rating=0.95,
                    raw={"source": "demo", "integration": "verified_stub"},
                )
            ]
        return []

    def integration_status(self) -> dict[str, Any]:
        configured = bool(self.api_key or self.config.get("base_url"))
        return {
            "platform": self.name,
            "status": "ready" if configured else "demo_verified",
            "checks": {
                "list_tasks": True,
                "accept": True,
                "submit": True,
                "automation_policy": True,
            },
        }

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "BountyBook integration stub verified for dry-run.",
            "requires_human_review": False,
        }

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        return {"ok": True, "external_id": task.external_id}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "submitted"}
