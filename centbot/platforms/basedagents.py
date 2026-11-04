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
        if not resp.content:
            return {"ok": False, "error": "empty_body", "status": resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {"ok": False, "error": "non_json_body", "status": resp.status_code}

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

    def register_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Register a BasedAgents identity when keypair can be created/saved."""
        from pathlib import Path

        from centbot.platforms.auth_basedagents import generate_identity, register_agent, save_identity_file

        try:
            identity = self.identity or generate_identity()
            identity = register_agent(
                self.client,
                name=str(payload.get("name") or "CENTBOT"),
                description="CENTBOT autonomous worker",
                capabilities=["code", "data", "content", "research", "automation"],
                identity=identity,
            )
            key_path = Path(str(self.config.get("keypair_path") or "data/basedagents-keypair.json"))
            save_identity_file(identity, key_path)
            self.identity = identity
            return {
                "ok": True,
                "status": "registered",
                "platform": self.name,
                "agent_id": identity.agent_id,
                "keypair": str(key_path),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "status": "error", "platform": self.name}

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        from centbot.platforms.response import interpret_platform_result

        if not self.identity:
            return {
                "ok": False,
                "error": "basedagents_identity_missing",
                "user_action": "run_python_-m_centbot_--register-basedagents_NAME",
            }
        path = f"/v1/tasks/{task.external_id}/claim"
        try:
            result = self._signed("POST", path, {})
            interpreted = interpret_platform_result(result, action="claim")
            return {**interpreted, "platform": self.name, "external_id": task.external_id}
        except PlatformHTTPError as exc:
            return _claim_http_error(exc, task.external_id)

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        from centbot.platforms.response import interpret_platform_result

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
            interpreted = interpret_platform_result(result, action="submit")
            if interpreted.get("ok"):
                interpreted["status"] = "submitted"
            return interpreted
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
        """Return raw payment payload; settlement is decided by confirm_payment, not this wrapper."""
        try:
            if self.identity:
                data = self._signed("GET", f"/v1/tasks/{task_id}/payment")
            else:
                data = self.client.get_json(f"/v1/tasks/{task_id}")
            return {"task_id": task_id, "payment": data}
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


def _claim_http_error(exc: PlatformHTTPError, external_id: str) -> dict[str, Any]:
    body = exc.body
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or "")
    lower = f"{msg} {exc}".lower()
    if exc.status == 409 or "already" in lower or "conflict" in lower or "claimed" in lower:
        return {
            "ok": False,
            "error": "already_claimed",
            "reason": "already_claimed",
            "status": 409,
            "body": body,
            "hint": "Uzdevums jau claimots / konflikts — izlaižam.",
            "external_id": external_id,
            "platform": "basedagents",
        }
    if exc.status == 404:
        return {
            "ok": False,
            "error": "task_gone",
            "reason": "task_gone",
            "status": 404,
            "body": body,
            "external_id": external_id,
            "platform": "basedagents",
        }
    return {
        "ok": False,
        "error": msg or str(exc),
        "status": exc.status,
        "body": body,
        "external_id": external_id,
        "platform": "basedagents",
    }


def _map_category(cat: Any) -> str:
    c = str(cat or "").lower()
    mapped = {
        "research": "text",
        "code": "programming",
        "content": "text",
        "data": "json_xml",
        "automation": "browser",
        "writing": "text",
        "analysis": "text",
        "general": "other",
    }.get(c)
    if mapped:
        return mapped
    # Unknown platform labels → generic (has fallback executor), not a dead category string
    return c if c in {"csv", "excel", "json_xml", "pdf", "image", "text", "programming", "browser", "android"} else "other"
