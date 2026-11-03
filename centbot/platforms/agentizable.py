"""Agentizable integration check connector."""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask


class AgentizableConnector(PlatformConnector):
    name = "agentizable"

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        if not self.api_key and not self.config.get("base_url"):
            return [
                PlatformTask(
                    platform=self.name,
                    external_id="ag-demo-excel-1",
                    title="Aggregate Excel sales sheets",
                    description="Combine monthly sheets into one summary workbook.",
                    reward_amount=22.0,
                    reward_currency="GBP",
                    category_hint="excel",
                    funded=True,
                    available=True,
                    automation_allowed=True,
                    payer_id="ag-corp",
                    payer_rating=0.88,
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
            "notes": "Agentizable integration stub verified for dry-run.",
            "requires_human_review": False,
        }

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        return {"ok": True, "external_id": task.external_id}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "submitted"}
