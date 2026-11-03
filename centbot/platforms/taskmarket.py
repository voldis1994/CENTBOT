"""TaskMarket live API — https://api.taskmarket.dev"""

from __future__ import annotations

from typing import Any, Callable

from centbot.platforms.auth_ethereum import (
    EthWallet,
    taskmarket_claim_message,
    taskmarket_read_message,
    taskmarket_submit_message,
    wallet_from_env,
    wallet_from_store,
)
from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.http import HttpClient, PlatformHTTPError


def _atomic_to_float(value: Any) -> float:
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return 0.0


class TaskMarketConnector(PlatformConnector):
    name = "taskmarket"

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str = "",
        wallet: EthWallet | None = None,
        credential_getter: Callable[[str], Any] | None = None,
    ):
        super().__init__(config, api_key)
        base = (config.get("base_url") or "https://api.taskmarket.dev").rstrip("/")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 30)))
        self.wallet = wallet or wallet_from_env(config.get("wallet_env", "CENTBOT_ETH_PRIVATE_KEY"))
        if self.wallet is None and credential_getter:
            self.wallet = wallet_from_store(credential_getter("eth_wallet"))
        self.min_reward = float(config.get("min_reward", 0) or 0)
        self.limit = int(config.get("limit", 50))
        self.mode = config.get("mode")  # bounty|claim|...

    def _caller_headers(self) -> dict[str, str]:
        if not self.wallet:
            return {}
        msg = taskmarket_read_message(self.wallet.address)
        sig = self.wallet.sign_message(msg)
        if not sig.startswith("0x"):
            sig = "0x" + sig
        return {
            "X-Taskmarket-Caller-Address": self.wallet.address,
            "X-Taskmarket-Caller-Signature": sig,
        }

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"limit": self.limit, "status": "open"}
        if self.mode:
            params["mode"] = self.mode
        data = self.client.get_json("/api/tasks", params=params, headers=self._caller_headers() or None)
        tasks = (data or {}).get("tasks") or []
        out: list[PlatformTask] = []
        for t in tasks:
            amount = _atomic_to_float(t.get("netReward") or t.get("reward"))
            if self.min_reward and amount < self.min_reward:
                continue
            tags = t.get("tags") or []
            escrow = t.get("escrowTxHash")
            funded = bool(escrow) or amount > 0
            out.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(t.get("id")),
                    title=_title_from_description(t.get("description")),
                    description=str(t.get("description") or ""),
                    reward_amount=amount,
                    reward_currency="USDC",
                    url=f"https://taskmarket.dev/tasks/{t.get('id')}",
                    category_hint=_hint_from_tags(tags),
                    payer_id=str(t.get("requester") or ""),
                    payer_rating=0.8 if t.get("requesterAgentId") else 0.7,
                    funded=funded,
                    available=str(t.get("status")) == "open",
                    claimable=str(t.get("status")) == "open" and not t.get("claimedBy"),
                    automation_allowed=True,
                    payment_state="escrowed" if escrow else "promised",
                    raw={"source": "taskmarket", "task": t},
                )
            )
        return out

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        if not self.wallet:
            return {"ok": False, "error": "wallet_required", "hint": "Set CENTBOT_ETH_PRIVATE_KEY or credentials eth_wallet"}
        msg = taskmarket_claim_message(task.external_id)
        sig = self.wallet.sign_message(msg)
        if not sig.startswith("0x"):
            sig = "0x" + sig
        body = {"workerAddress": self.wallet.address, "signature": sig}
        try:
            result = self.client.post_json(f"/api/tasks/{task.external_id}/claim", body, headers=self._caller_headers())
            from centbot.platforms.response import interpret_platform_result

            interpreted = interpret_platform_result(result, action="claim")
            return {**interpreted, "external_id": task.external_id}
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.wallet:
            return {"ok": False, "error": "wallet_required"}
        msg = taskmarket_submit_message(task.external_id)
        sig = self.wallet.sign_message(msg)
        if not sig.startswith("0x"):
            sig = "0x" + sig
        content = payload.get("content")
        if content is None:
            content = payload.get("output")
        if content is None:
            content = {"summary": payload.get("summary"), "evidence": payload.get("evidence")}
        if not isinstance(content, str):
            import json

            content = json.dumps(content, ensure_ascii=False)
        body = {
            "workerAddress": self.wallet.address,
            "signature": sig,
            "content": content,
        }
        try:
            result = self.client.post_json(
                f"/api/tasks/{task.external_id}/submissions",
                body,
                headers=self._caller_headers(),
            )
            from centbot.platforms.response import interpret_platform_result

            interpreted = interpret_platform_result(result, action="submit")
            if interpreted.get("ok"):
                interpreted["status"] = "submitted"
            return interpreted
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def check_submission_status(self, submission_id: str) -> dict[str, Any]:
        try:
            data = self.client.get_json(f"/api/tasks/{submission_id}", headers=self._caller_headers() or None)
            task = data if isinstance(data, dict) else {}
            return {"submission_id": submission_id, "status": task.get("status") or "unknown", "task": task}
        except PlatformHTTPError as exc:
            return {"submission_id": submission_id, "status": "error", "error": str(exc)}

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Official REST API. Wallet EIP-191 signatures required for claim/submit.",
            "requires_human_review": False,
            "wallet_loaded": bool(self.wallet),
        }

    def health(self) -> dict[str, Any]:
        try:
            data = self.client.get_json("/api/tasks", params={"limit": 1, "status": "open"})
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": True,
                "wallet_loaded": bool(self.wallet),
                "sample_count": len((data or {}).get("tasks") or []),
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


def _title_from_description(desc: Any) -> str:
    text = str(desc or "").strip().splitlines()
    if not text:
        return "TaskMarket task"
    title = text[0].strip()
    return title[:120] if title else "TaskMarket task"


def _hint_from_tags(tags: list[Any]) -> str:
    joined = " ".join(str(t).lower() for t in tags)
    if any(x in joined for x in ("code", "python", "dev")):
        return "programming"
    if "writ" in joined or "content" in joined:
        return "text"
    if "data" in joined:
        return "json_xml"
    return "other"
