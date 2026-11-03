"""BountyBook live API connector — https://api.bountybook.ai (configurable)."""

from __future__ import annotations

from typing import Any, Callable

from centbot.platforms.auth_ethereum import EthWallet, wallet_from_env, wallet_from_store
from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.http import HttpClient, PlatformHTTPError


class BountyBookConnector(PlatformConnector):
    name = "bountybook"

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str = "",
        wallet: EthWallet | None = None,
        credential_getter: Callable[[str], Any] | None = None,
    ):
        super().__init__(config, api_key)
        base = (config.get("base_url") or "https://api.bountybook.ai").rstrip("/")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 30)))
        self.wallet = wallet or wallet_from_env(config.get("wallet_env", "CENTBOT_ETH_PRIVATE_KEY"))
        if self.wallet is None and credential_getter:
            self.wallet = wallet_from_store(credential_getter("eth_wallet"))
        self.bearer = api_key or (credential_getter("bountybook_token") if credential_getter else None) or ""
        if isinstance(self.bearer, dict):
            self.bearer = str(self.bearer.get("token") or "")
        self.min_reward = float(config.get("min_reward", 0) or 0)
        self.limit = int(config.get("limit", 50))
        self.category = config.get("category")

    def _auth_headers(self) -> dict[str, str]:
        if not self.bearer:
            return {}
        return {"Authorization": f"Bearer {self.bearer}"}

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"status": "open", "limit": self.limit}
        if self.category:
            params["category"] = self.category
        try:
            data = self.client.get_json("/jobs", params=params)
        except PlatformHTTPError:
            # Some deployments nest under /api
            data = self.client.get_json("/api/jobs", params=params)
        jobs = []
        if isinstance(data, list):
            jobs = data
        elif isinstance(data, dict):
            jobs = data.get("jobs") or data.get("items") or data.get("data") or []
        out: list[PlatformTask] = []
        for j in jobs:
            try:
                amount = float(j.get("budget_usdc") or j.get("budget") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            if self.min_reward and amount < self.min_reward:
                continue
            out.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(j.get("id")),
                    title=str(j.get("title") or "BountyBook job"),
                    description=str(j.get("description") or (j.get("spec") or {}).get("instructions") or ""),
                    reward_amount=amount,
                    reward_currency="USDC",
                    url=f"https://www.bountybook.ai/jobs/{j.get('id')}",
                    category_hint=_map_cat(j.get("job_type") or j.get("category")),
                    payer_id=str(j.get("posterAddress") or ""),
                    payer_rating=0.85,
                    funded=amount > 0,
                    available=str(j.get("status")) == "open",
                    claimable=str(j.get("status")) == "open",
                    automation_allowed=True,
                    payment_state="escrowed" if amount > 0 else "unknown",
                    raw={"source": "bountybook", "job": j},
                )
            )
        return out

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        if not self.bearer:
            return {
                "ok": False,
                "error": "auth_required",
                "hint": "Set BOUNTYBOOK_API_KEY bearer token from wallet nonce login",
            }
        addr = self.wallet.address if self.wallet else None
        body = {"agentAddress": addr, "executorAddress": addr}
        try:
            from centbot.platforms.response import interpret_platform_result

            result = self.client.post_json(f"/jobs/{task.external_id}/claim", body, headers=self._auth_headers())
            interpreted = interpret_platform_result(result, action="claim")
            return {**interpreted, "external_id": task.external_id}
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.bearer:
            return {"ok": False, "error": "auth_required"}
        addr = self.wallet.address if self.wallet else payload.get("executorAddress")
        body = {
            "executorAddress": addr,
            "outputData": payload.get("output") or payload.get("outputData") or payload,
        }
        try:
            from centbot.platforms.response import interpret_platform_result

            result = self.client.post_json(f"/jobs/{task.external_id}/submit", body, headers=self._auth_headers())
            if isinstance(result, dict):
                passed = (result.get("verification_result") or result.get("verification") or {}).get("passed")
                if passed is None:
                    passed = result.get("passed")
                if passed is False:
                    return {"ok": False, "error": "verification_failed", "status": "rejected", "result": result}
            interpreted = interpret_platform_result(result, action="submit")
            if interpreted.get("ok"):
                interpreted["status"] = "submitted"
            return interpreted
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def check_submission_status(self, submission_id: str) -> dict[str, Any]:
        try:
            data = self.client.get_json(f"/jobs/{submission_id}/status")
            return {"submission_id": submission_id, "status": (data or {}).get("status", "unknown"), "raw": data}
        except PlatformHTTPError as exc:
            return {"submission_id": submission_id, "status": "error", "error": str(exc)}

    def integration_status(self) -> dict[str, Any]:
        h = self.health()
        return {
            "platform": self.name,
            "status": "ready" if h.get("live") else "unreachable",
            "checks": {
                "list_tasks": bool(h.get("live")),
                "accept": bool(self.bearer),
                "submit": bool(self.bearer),
                "automation_policy": True,
            },
            "health": h,
        }

    def health(self) -> dict[str, Any]:
        try:
            data = self.client.get_json("/jobs", params={"status": "open", "limit": 1})
            jobs = data if isinstance(data, list) else (data or {}).get("jobs") or []
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": True,
                "auth_loaded": bool(self.bearer),
                "sample_count": len(jobs),
            }
        except PlatformHTTPError as exc:
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": False,
                "error": str(exc),
                "hint": "Host may be unreachable from this network; set platforms.bountybook.base_url if mirrored.",
            }


def _map_cat(cat: Any) -> str:
    c = str(cat or "").lower()
    return {
        "research": "text",
        "code": "programming",
        "data": "json_xml",
        "content": "text",
        "scrape": "browser",
        "transform": "json_xml",
        "fetch": "browser",
        "workflow": "browser",
        "monitor": "other",
    }.get(c, c or "other")
