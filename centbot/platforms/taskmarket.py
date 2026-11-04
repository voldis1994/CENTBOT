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


def _sig_hex(sig: str) -> str:
    return sig if sig.startswith("0x") else "0x" + sig


def _hire_blocks_worker(task: dict[str, Any], worker_address: str | None) -> bool:
    """True when a hire reservation exists for a different wallet."""
    hire = task.get("hire")
    if not isinstance(hire, dict) or not hire:
        return False
    reserved = str(hire.get("worker") or "").strip()
    if not reserved:
        return False
    if not worker_address:
        return True
    return reserved.lower() != worker_address.lower()


def _skip_reason(task: dict[str, Any], worker_address: str | None) -> str | None:
    """Why a TaskMarket row must not be auto-accepted (None = workable)."""
    status = str(task.get("status") or "open").lower()
    if status and status != "open":
        return "unavailable"
    if task.get("claimedBy"):
        return "already_claimed"
    mode = str(task.get("mode") or "").lower()
    if mode in {"pitch", "auction"}:
        return "not_claim_mode"
    if mode == "claim":
        if bool(task.get("stakeRequired")):
            return "stake_payment_required"
        if _hire_blocks_worker(task, worker_address):
            return "hire_reserved"
        return None
    # bounty / benchmark: no /claim step — local accept then submit
    if mode in {"bounty", "benchmark", ""}:
        return None
    return "not_claim_mode"


def _is_auto_claimable(task: dict[str, Any], worker_address: str | None) -> bool:
    """True when CENTBOT can auto-accept (claim or bounty direct-submit)."""
    return _skip_reason(task, worker_address) is None


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
        # None/empty = all open modes (bounty + claim). Stake/hire still soft-skipped.
        self.mode = config.get("mode") or None
        self.allow_stake_claims = bool(config.get("allow_stake_claims", False))

    def _caller_headers(self) -> dict[str, str]:
        if not self.wallet:
            return {}
        msg = taskmarket_read_message(self.wallet.address)
        sig = _sig_hex(self.wallet.sign_message(msg))
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
        worker = self.wallet.address if self.wallet else None
        out: list[PlatformTask] = []
        for t in tasks:
            amount = _atomic_to_float(t.get("netReward") or t.get("reward"))
            if self.min_reward and amount < self.min_reward:
                continue
            tags = t.get("tags") or []
            escrow = t.get("escrowTxHash")
            funded = bool(escrow) or amount > 0
            skip = _skip_reason(t, worker)
            claimable = skip is None
            raw_meta: dict[str, Any] = {"source": "taskmarket", "task": t}
            if skip:
                raw_meta["skip_reason"] = skip
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
                    claimable=claimable,
                    automation_allowed=True,
                    payment_state="escrowed" if escrow else "promised",
                    raw=raw_meta,
                )
            )
        return out

    def register_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """TaskMarket identity = Ethereum wallet. Confirm wallet can authenticate against API."""
        if not self.wallet:
            return {
                "ok": False,
                "error": "wallet_required",
                "platform": self.name,
                "status": "error",
                "user_action": "set_CENTBOT_ETH_PRIVATE_KEY_or_store_eth_wallet_credential",
            }
        try:
            headers = self._caller_headers()
            # Probe authenticated read — wallet presence is the account
            self.client.get_json("/api/tasks", params={"limit": 1}, headers=headers)
            return {
                "ok": True,
                "status": "registered",
                "platform": self.name,
                "worker_address": self.wallet.address,
                "note": "TaskMarket uses wallet signatures; no separate signup API",
            }
        except PlatformHTTPError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "status": exc.status,
                "platform": self.name,
                "worker_address": self.wallet.address,
                "body": exc.body,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "platform": self.name, "status": "error"}

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        if not self.wallet:
            return {
                "ok": False,
                "error": "wallet_required",
                "hint": "Set CENTBOT_ETH_PRIVATE_KEY or credentials eth_wallet",
                "user_action": "SET_ETH_KEY.bat",
            }
        raw_task = (task.raw or {}).get("task") if isinstance(task.raw, dict) else None
        if not isinstance(raw_task, dict):
            raw_task = {}

        mode = str(raw_task.get("mode") or "").lower()
        # Bounty/benchmark: no /claim — book locally and submit artifacts later.
        if mode in {"bounty", "benchmark"}:
            return {
                "ok": True,
                "mode": "direct_submit",
                "external_id": task.external_id,
                "note": "bounty/benchmark — claim nav vajadzīgs, iesniegšana caur /submissions",
            }
        if mode in {"pitch", "auction"}:
            return {
                "ok": False,
                "error": "not_claim_mode",
                "reason": "not_claim_mode",
                "status": 400,
                "hint": "Pitch/auction nav auto-claim — vajag citu TaskMarket plūsmu.",
                "external_id": task.external_id,
            }
        skip = _skip_reason(raw_task, self.wallet.address)
        if skip == "stake_payment_required" and not self.allow_stake_claims:
            return {
                "ok": False,
                "error": "stake_payment_required",
                "reason": "stake_payment_required",
                "status": 402,
                "hint": "Šim claim vajag x402 stake (~1 USDC Base) — izlaists, kamēr stake nav ieslēgts.",
                "external_id": task.external_id,
            }
        if skip == "hire_reserved":
            hire = raw_task.get("hire") if isinstance(raw_task.get("hire"), dict) else {}
            return {
                "ok": False,
                "error": "hire_reserved",
                "reason": "hire_reserved",
                "status": 403,
                "hint": f"Hire rezervēts citam worker: {hire.get('worker')}",
                "external_id": task.external_id,
            }
        if skip and skip not in {"stake_payment_required"}:
            return {
                "ok": False,
                "error": skip,
                "reason": skip,
                "external_id": task.external_id,
            }

        msg = taskmarket_claim_message(task.external_id)
        sig = _sig_hex(self.wallet.sign_message(msg))
        # OpenAPI requires workerAddress+signature; taskId in body is accepted and documented elsewhere.
        body = {
            "taskId": task.external_id,
            "workerAddress": self.wallet.address,
            "signature": sig,
        }
        try:
            result = self.client.post_json(
                f"/api/tasks/{task.external_id}/claim",
                body,
                headers=self._caller_headers(),
            )
            from centbot.platforms.response import interpret_platform_result

            interpreted = interpret_platform_result(result, action="claim")
            return {**interpreted, "external_id": task.external_id, "signed_message": msg}
        except PlatformHTTPError as exc:
            return _claim_http_error(exc, task.external_id)

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.wallet:
            return {"ok": False, "error": "wallet_required"}
        msg = taskmarket_submit_message(task.external_id)
        sig = _sig_hex(self.wallet.sign_message(msg))
        content = payload.get("content")
        if content is None:
            content = payload.get("output")
        if content is None:
            content = {"summary": payload.get("summary"), "evidence": payload.get("evidence")}
        if not isinstance(content, str):
            import json

            content = json.dumps(content, ensure_ascii=False)
        body = {
            "taskId": task.external_id,
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


def _claim_http_error(exc: PlatformHTTPError, external_id: str) -> dict[str, Any]:
    body = exc.body
    msg = ""
    code = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or "")
        code = str(body.get("code") or "")
    lower = msg.lower()
    if exc.status == 402 or "payment required" in lower or "claim stake" in lower:
        return {
            "ok": False,
            "error": "stake_payment_required",
            "reason": "stake_payment_required",
            "status": 402,
            "body": body,
            "hint": "TaskMarket pieprasa x402 claim stake (Base USDC) — izlaid, līdz stake ir apmaksāts.",
            "external_id": external_id,
        }
    if exc.status == 401 or "signature does not match" in lower:
        return {
            "ok": False,
            "error": "signature_mismatch",
            "reason": "signature_mismatch",
            "status": 401,
            "body": body,
            "hint": "Paraksts nesakrīt ar workerAddress — pārbaudi ETH private key un claim message formātu.",
            "external_id": external_id,
        }
    if "not a claim task" in lower:
        return {
            "ok": False,
            "error": "not_claim_mode",
            "reason": "not_claim_mode",
            "status": exc.status or 400,
            "body": body,
            "hint": "Nav Claim task — bounty/pitch nevar claimot ar /claim.",
            "external_id": external_id,
        }
    if "hire offered to another" in lower or (exc.status == 403 and "hire" in lower):
        return {
            "ok": False,
            "error": "hire_reserved",
            "reason": "hire_reserved",
            "status": 403,
            "body": body,
            "hint": "Hire rezervēts citam worker.",
            "external_id": external_id,
        }
    return {
        "ok": False,
        "error": msg or str(exc),
        "status": exc.status,
        "body": body,
        "code": code or None,
        "external_id": external_id,
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
    if any(x in joined for x in ("web", "browser", "scrape", "autom")):
        return "browser"
    # Prefer text over dead "other" so PC worker can deliver
    return "text"
