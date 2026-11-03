"""Agentizable live API — https://api.agentizable.ai"""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.http import HttpClient, PlatformHTTPError


class AgentizableConnector(PlatformConnector):
    name = "agentizable"

    def __init__(self, config: dict[str, Any], api_key: str = ""):
        super().__init__(config, api_key)
        base = (config.get("base_url") or "https://api.agentizable.ai").rstrip("/")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 45)))
        self.network = str(config.get("network", "base-mainnet"))
        self.min_reward = float(config.get("min_reward", 0) or 0)
        self.claimable_only = bool(config.get("claimable_only", True))

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        tasks: list[PlatformTask] = []
        # Primary: opportunities projection
        try:
            data = self.client.get_json("/v1/opportunities")
            items = (data or {}).get("items") or []
            for item in items:
                tasks.append(self._from_opportunity(item))
        except PlatformHTTPError:
            pass
        # Canonical claimable feed
        try:
            feed = self.client.get_json(
                "/v1/base/autonomous-bounties/feed",
                params={"network": self.network, "claimable_only": str(self.claimable_only).lower()},
            )
            items = []
            if isinstance(feed, dict):
                items = feed.get("items") or feed.get("bounties") or feed.get("results") or []
            elif isinstance(feed, list):
                items = feed
            for item in items:
                tasks.append(self._from_bounty(item))
        except PlatformHTTPError:
            pass
        # Dedup by external_id
        seen: set[str] = set()
        unique: list[PlatformTask] = []
        for t in tasks:
            if t.external_id in seen:
                continue
            if self.min_reward and t.reward_amount < self.min_reward:
                continue
            seen.add(t.external_id)
            unique.append(t)
        return unique

    def _from_opportunity(self, item: dict[str, Any]) -> PlatformTask:
        reward = item.get("reward") or item.get("bounty") or {}
        amount = reward.get("amount") if isinstance(reward, dict) else item.get("reward_amount")
        try:
            amount_f = float(amount or 0)
        except (TypeError, ValueError):
            amount_f = 0.0
        ext = str(item.get("id") or item.get("opportunity_id") or item.get("bounty_id") or "")
        payment_state = str(item.get("payment_state") or reward.get("state") if isinstance(reward, dict) else "" or "")
        return PlatformTask(
            platform=self.name,
            external_id=ext or str(hash(str(item))),
            title=str(item.get("title") or item.get("name") or "Agentizable opportunity"),
            description=str(item.get("description") or item.get("summary") or ""),
            reward_amount=amount_f,
            reward_currency=str((reward.get("currency") if isinstance(reward, dict) else None) or "USDC"),
            url=str(item.get("url") or item.get("authorization_url") or "https://agentizable.ai/earn.html"),
            category_hint="programming",
            payer_id=str(item.get("creator") or ""),
            payer_rating=0.9 if payment_state == "escrowed" else 0.7,
            funded=payment_state in {"escrowed", "funded"} or amount_f > 0,
            available=True,
            claimable=bool(item.get("claimable", True)),
            automation_allowed=True,
            payment_state=payment_state,
            raw={"source": "agentizable", "opportunity": item},
        )

    def _from_bounty(self, item: dict[str, Any]) -> PlatformTask:
        amount = item.get("reward_usdc") or item.get("amount") or (item.get("reward") or {}).get("amount")
        try:
            amount_f = float(amount or 0)
        except (TypeError, ValueError):
            amount_f = 0.0
        ext = str(item.get("id") or item.get("bounty_id") or item.get("address") or "")
        return PlatformTask(
            platform=self.name,
            external_id=ext or str(hash(str(item))),
            title=str(item.get("title") or "Agentizable bounty"),
            description=str(item.get("description") or item.get("acceptance_criteria") or ""),
            reward_amount=amount_f,
            reward_currency="USDC",
            url=str(item.get("url") or "https://agentizable.ai/earn.html"),
            category_hint="programming",
            payer_rating=0.9,
            funded=True,
            available=True,
            claimable=True,
            automation_allowed=True,
            payment_state="escrowed",
            raw={"source": "agentizable", "bounty": item},
        )

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        # Agentizable requires first-party authorization_url confirmation — never silent wallet signing.
        return {
            "ok": False,
            "reason": "human_authorization_required",
            "handoff_url": task.url or "https://agentizable.ai/earn.html",
            "message": "Use Agentizable MCP/prepare_bounty_action; confirm wallet on first-party authorization_url.",
            "external_id": task.external_id,
        }

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "reason": "human_authorization_required",
            "handoff_url": task.url,
            "payload_keys": list(payload.keys()),
            "message": "Complete/verify via Agentizable first-party flow after claim is confirmed on-chain.",
        }

    def integration_status(self) -> dict[str, Any]:
        h = self.health()
        return {
            "platform": self.name,
            "status": "ready" if h.get("live") else "degraded",
            "checks": {
                "list_tasks": bool(h.get("live")),
                "accept": False,  # requires human auth URL
                "submit": False,
                "automation_policy": True,
            },
            "health": h,
        }

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Discovery via REST is live. Claims require human-confirmed first-party authorization_url.",
            "requires_human_review": True,
        }

    def health(self) -> dict[str, Any]:
        try:
            data = self.client.get_json("/v1/opportunities")
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": True,
                "degraded": bool((data or {}).get("degraded")),
                "item_count": len((data or {}).get("items") or []),
            }
        except PlatformHTTPError as exc:
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": False,
                "error": str(exc),
            }
