"""BasedAgents connector."""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask


class BasedAgentsConnector(PlatformConnector):
    name = "basedagents"

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        if not self.api_key and not self.config.get("base_url"):
            return [
                PlatformTask(
                    platform=self.name,
                    external_id="ba-demo-json-1",
                    title="Transform JSON config into XML report",
                    description="Convert nested JSON to a validated XML document.",
                    reward_amount=18.0,
                    reward_currency="USD",
                    category_hint="json_xml",
                    funded=True,
                    available=True,
                    automation_allowed=True,
                    payer_id="ba-payer-1",
                    payer_rating=0.85,
                    raw={"source": "demo"},
                )
            ]
        return []

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Agent API automation permitted when key present.",
            "requires_human_review": False,
        }

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        return {"ok": True, "platform": self.name, "external_id": task.external_id}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "submitted", "external_id": task.external_id}
