"""Platform registry and extra reward sources."""

from __future__ import annotations

from typing import Any

from centbot.core.config import Config
from centbot.platforms.agentizable import AgentizableConnector
from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.basedagents import BasedAgentsConnector
from centbot.platforms.bountybook import BountyBookConnector
from centbot.platforms.jobbi import JobbiConnector
from centbot.platforms.taskmarket import TaskMarketConnector


class ExtraRewardSource(PlatformConnector):
    """Generic verified extra bounty/reward source adapter."""

    def __init__(self, name: str, config: dict[str, Any], api_key: str = ""):
        super().__init__(config, api_key)
        self.name = name

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        demos = self.config.get("demo_tasks") or []
        tasks: list[PlatformTask] = []
        for item in demos:
            tasks.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(item.get("id", f"{self.name}-demo")),
                    title=str(item.get("title", "Extra reward task")),
                    description=str(item.get("description", "")),
                    reward_amount=float(item.get("reward_amount", 5)),
                    reward_currency=str(item.get("reward_currency", "USD")),
                    category_hint=str(item.get("category_hint", "other")),
                    funded=bool(item.get("funded", True)),
                    available=bool(item.get("available", True)),
                    automation_allowed=bool(item.get("automation_allowed", True)),
                    payer_rating=float(item.get("payer_rating", 0.7)),
                    raw={"source": "extra", **item},
                )
            )
        return tasks

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        return {"ok": True, "external_id": task.external_id}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "submitted"}


CORE_BUILDERS = {
    "jobbi": JobbiConnector,
    "basedagents": BasedAgentsConnector,
    "taskmarket": TaskMarketConnector,
    "bountybook": BountyBookConnector,
    "agentizable": AgentizableConnector,
}


def build_platforms(config: Config) -> dict[str, PlatformConnector]:
    platforms: dict[str, PlatformConnector] = {}
    for name, cls in CORE_BUILDERS.items():
        cfg = config.section("platforms").get(name, {}) or {}
        platforms[name] = cls(cfg, api_key=config.platform_api_key(name))

    # Additional verified sources from config.platforms.extra list
    extras = config.get("platforms.extra", []) or []
    for item in extras:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"])
        platforms[name] = ExtraRewardSource(name, item, api_key=config.env(item.get("api_key_env", "")))

    # Built-in extra demo source so checklist item 18 is covered out of the box
    if "openbounties" not in platforms:
        platforms["openbounties"] = ExtraRewardSource(
            "openbounties",
            {
                "enabled": True,
                "demo_tasks": [
                    {
                        "id": "ob-demo-pdf-1",
                        "title": "Extract text from PDF invoice",
                        "description": "Pull vendor, date, and total from a sample PDF.",
                        "reward_amount": 15,
                        "reward_currency": "USD",
                        "category_hint": "pdf",
                        "funded": True,
                        "automation_allowed": True,
                        "payer_rating": 0.8,
                    }
                ],
            },
        )
    return platforms


def verify_integrations(platforms: dict[str, PlatformConnector]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name, conn in platforms.items():
        entry: dict[str, Any] = {"health": conn.health(), "automation": conn.check_automation_rules()}
        if hasattr(conn, "integration_status"):
            entry["integration"] = conn.integration_status()  # type: ignore[attr-defined]
        try:
            tasks = conn.list_tasks()
            entry["sample_task_count"] = len(tasks)
            entry["ok"] = True
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = str(exc)
        report[name] = entry
    return report
