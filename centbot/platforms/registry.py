"""Platform registry — live connectors only (no demo catalogs)."""

from __future__ import annotations

from typing import Any, Callable

from centbot.core.config import Config
from centbot.platforms.agentizable import AgentizableConnector
from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.basedagents import BasedAgentsConnector
from centbot.platforms.bountybook import BountyBookConnector
from centbot.platforms.jobbi import JobbiConnector
from centbot.platforms.taskmarket import TaskMarketConnector


class ExtraRewardSource(PlatformConnector):
    """Configurable extra live HTTP source.

    Expected config:
      name, base_url, list_path, enabled
      item_map optional field mapping
    """

    def __init__(self, name: str, config: dict[str, Any], api_key: str = ""):
        super().__init__(config, api_key)
        self.name = name
        from centbot.platforms.http import HttpClient

        base = (config.get("base_url") or "").rstrip("/")
        if not base:
            raise ValueError(f"extra platform {name} requires base_url")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 30)))
        self.list_path = str(config.get("list_path") or "/tasks")
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        data = self.client.get_json(self.list_path, headers=self.headers or None)
        items = data if isinstance(data, list) else (data or {}).get("tasks") or (data or {}).get("items") or []
        fmap = self.config.get("item_map") or {}
        out: list[PlatformTask] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(item.get(fmap.get("id", "id"))),
                    title=str(item.get(fmap.get("title", "title")) or f"{self.name} task"),
                    description=str(item.get(fmap.get("description", "description")) or ""),
                    reward_amount=float(item.get(fmap.get("reward", "reward_amount")) or 0),
                    reward_currency=str(item.get(fmap.get("currency", "reward_currency")) or "USD"),
                    url=str(item.get(fmap.get("url", "url")) or ""),
                    funded=bool(item.get("funded", True)),
                    available=bool(item.get("available", True)),
                    claimable=bool(item.get("claimable", True)),
                    automation_allowed=bool(item.get("automation_allowed", True)),
                    raw={"source": self.name, "item": item},
                )
            )
        return out

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        from centbot.platforms.response import interpret_platform_result

        path = str(self.config.get("claim_path") or f"/tasks/{task.external_id}/claim")
        path = path.replace("{id}", task.external_id)
        result = self.client.post_json(path, {}, headers=self.headers or None)
        return {**interpret_platform_result(result, action="claim"), "external_id": task.external_id}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        from centbot.platforms.response import interpret_platform_result

        path = str(self.config.get("submit_path") or f"/tasks/{task.external_id}/submit")
        path = path.replace("{id}", task.external_id)
        result = self.client.post_json(path, payload, headers=self.headers or None)
        interpreted = interpret_platform_result(result, action="submit")
        if interpreted.get("ok"):
            interpreted["status"] = "submitted"
        return interpreted


def build_platforms(
    config: Config,
    credential_getter: Callable[[str], Any] | None = None,
) -> dict[str, PlatformConnector]:
    platforms: dict[str, PlatformConnector] = {}
    platforms["jobbi"] = JobbiConnector(config.section("platforms").get("jobbi", {}) or {})
    platforms["basedagents"] = BasedAgentsConnector(
        config.section("platforms").get("basedagents", {}) or {},
        api_key=config.platform_api_key("basedagents"),
        credential_getter=credential_getter,
    )
    platforms["taskmarket"] = TaskMarketConnector(
        config.section("platforms").get("taskmarket", {}) or {},
        api_key=config.platform_api_key("taskmarket"),
        credential_getter=credential_getter,
    )
    platforms["bountybook"] = BountyBookConnector(
        config.section("platforms").get("bountybook", {}) or {},
        api_key=config.platform_api_key("bountybook"),
        credential_getter=credential_getter,
    )
    platforms["agentizable"] = AgentizableConnector(config.section("platforms").get("agentizable", {}) or {})

    extras = config.get("platforms.extra", []) or []
    for item in extras:
        if not isinstance(item, dict) or not item.get("name") or not item.get("base_url"):
            continue
        name = str(item["name"])
        platforms[name] = ExtraRewardSource(name, item, api_key=config.env(item.get("api_key_env", "")))
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
            # Reachable API ≠ market success; ok means discovery worked without error
            entry["ok"] = True
            entry["live"] = True
            entry["discovery_only"] = len(tasks) == 0
            if tasks:
                entry["sample"] = {
                    "id": tasks[0].external_id,
                    "title": tasks[0].title[:80],
                    "reward": tasks[0].reward_amount,
                    "currency": tasks[0].reward_currency,
                }
            else:
                entry["note"] = "API reachable but returned zero open tasks"
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["live"] = False
            err = str(exc)
            low = err.lower()
            if any(x in low for x in ("platform_offline", "failed to resolve", "getaddrinfo", "11001", "nxdomain")):
                entry["offline"] = True
                entry["error"] = err[:180]
                entry["note"] = "Platform host unreachable (DNS/offline) — not a local CENTBOT misconfig"
            else:
                entry["error"] = err[:220]
        report[name] = entry
    return report

