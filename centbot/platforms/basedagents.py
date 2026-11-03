"""BasedAgents live marketplace — https://api.basedagents.ai"""

from __future__ import annotations

import json
from typing import Any, Callable

from centbot.platforms.auth_basedagents import BasedAgentsIdentity, resolve_identity, sign_headers
from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.http import HttpClient, PlatformHTTPError


class BasedAgentsConnector(PlatformConnector):
    name = "basedagents"

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str = "",
        identity: BasedAgentsIdentity | None = None,
        credential_getter: Callable[[str], Any] | None = None,
    ):
        super().__init__(config, api_key)
        base = (config.get("base_url") or "https://api.basedagents.ai").rstrip("/")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 30)))
        self.identity = identity or resolve_identity(config, credential_getter)
        self.min_usdc = float(config.get("min_usdc", 0) or 0)
        self.category = config.get("category")
        self.limit = int(config.get("limit", 50))

    def _signed(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if not self.identity:
            raise PlatformHTTPError("BasedAgents identity required (keypair_path / BASEDAGENTS_KEYPAIR_PATH)")
        raw = b"" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = sign_headers(self.identity, method, path, raw)
        if method.upper() == "GET":
            return self.client.get_json(path, headers=headers)
        resp = self.client.request(method, path, json_body=body, headers=headers)
        return resp.json() if resp.content else {"ok": True}

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"status": "open", "limit": self.limit}
        if self.category:
            params["category"] = self.category
        data = self.client.get_json("/v1/tasks", params=params)
        tasks = (data or {}).get("tasks") or []
        out: list[PlatformTask] = []
        for t in tasks:
            bounty = t.get("bounty") or {}
            amount = bounty.get("amount_display")
            if amount is None and t.get("bounty_amount") is not None:
                try:
                    amount = float(t["bounty_amount"]) / 1_000_000.0
                except (TypeError, ValueError):
                    amount = 0.0
            try:
                amount_f = float(amount or 0)
            except (TypeError, ValueError):
                amount_f = 0.0
            if self.min_usdc and amount_f < self.min_usdc:
                continue
            escrow = t.get("escrow") or {}
            funded = (escrow.get("status") == "funded") or (amount_f > 0 and bool(t.get("claimable")))
            currency = str(bounty.get("token") or t.get("bounty_token") or "USDC")
            out.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(t.get("task_id") or t.get("id")),
                    title=str(t.get("title") or "BasedAgents task"),
                    description=str(t.get("description") or ""),
                    reward_amount=amount_f,
                    reward_currency=currency,
                    url=f"https://app.basedagents.ai/tasks/{t.get('task_id') or t.get('id')}",
                    category_hint=_map_category(t.get("category")),
                    payer_id=str(t.get("creator_agent_id") or t.get("creator_kind") or ""),
                    payer_rating=0.85,
                    funded=bool(funded),
                    available=str(t.get("status")) == "open",
                    claimable=bool(t.get("claimable", True)),
                    automation_allowed=True,
                    payment_state=str((escrow.get("status") if escrow else None) or t.get("payment_status") or ""),
                    raw={"source": "basedagents", "task": t},
                )
            )
        return out

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        path = f"/v1/tasks/{task.external_id}/claim"
        try:
            result = self._signed("POST", path, {})
            return {"ok": True, "platform": self.name, "external_id": task.external_id, "result": result}
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": payload.get("summary") or payload.get("note") or f"CENTBOT delivery for {task.external_id}",
        }
        if payload.get("content") is not None:
            body["content"] = payload["content"]
        elif payload.get("output") is not None:
            body["content"] = payload["output"]
        if payload.get("pr_url"):
            body["pr_url"] = payload["pr_url"]
        if payload.get("artifact"):
            body["artifact"] = payload["artifact"]
        if payload.get("evidence"):
            body.setdefault("content", {})
            if isinstance(body["content"], dict):
                body["content"]["evidence"] = payload["evidence"]
            else:
                body["evidence"] = payload["evidence"]
        path = f"/v1/tasks/{task.external_id}/deliver"
        try:
            result = self._signed("POST", path, body)
            return {"ok": True, "status": "submitted", "result": result}
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def check_submission_status(self, submission_id: str) -> dict[str, Any]:
        # submission_id treated as task_id
        try:
            data = self.client.get_json(f"/v1/tasks/{submission_id}")
            task = (data or {}).get("task") or data or {}
            return {
                "submission_id": submission_id,
                "status": task.get("status") or "unknown",
                "payment_status": task.get("payment_status"),
                "review_state": task.get("review_state"),
            }
        except PlatformHTTPError as exc:
            return {"submission_id": submission_id, "status": "error", "error": str(exc)}

    def check_payment(self, task_id: str) -> dict[str, Any]:
        try:
            if self.identity:
                data = self._signed("GET", f"/v1/tasks/{task_id}/payment")
            else:
                data = self.client.get_json(f"/v1/tasks/{task_id}")
            return {"ok": True, "task_id": task_id, "payment": data}
        except PlatformHTTPError as exc:
            return {"ok": False, "task_id": task_id, "error": str(exc), "body": exc.body}

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Official AgentSig API. Identity keypair required for claim/deliver.",
            "requires_human_review": False,
            "identity_loaded": bool(self.identity),
        }

    def health(self) -> dict[str, Any]:
        try:
            status = self.client.get_json("/v1/health")
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": True,
                "identity_loaded": bool(self.identity),
                "health": status,
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


def _map_category(cat: Any) -> str:
    c = str(cat or "").lower()
    return {
        "research": "text",
        "code": "programming",
        "content": "text",
        "data": "json_xml",
        "automation": "browser",
    }.get(c, c or "other")
