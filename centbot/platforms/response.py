"""Honest interpretation of platform HTTP/JSON responses — never default success."""

from __future__ import annotations

from typing import Any


def interpret_platform_result(result: Any, *, action: str = "request") -> dict[str, Any]:
    """Map a platform JSON body to ``ok`` without assuming success on empty payloads."""
    if result is None:
        return {"ok": False, "error": "empty_response", "action": action}
    if not isinstance(result, dict):
        return {"ok": False, "error": "non_object_response", "action": action, "result": result}

    # Explicit failure signals
    if result.get("ok") is False or result.get("success") is False or result.get("error"):
        return {
            "ok": False,
            "error": result.get("error") or result.get("message") or "platform_reported_failure",
            "action": action,
            "result": result,
        }
    if str(result.get("status") or "").lower() in {"failed", "error", "rejected", "denied"}:
        return {"ok": False, "error": f"platform_status:{result.get('status')}", "action": action, "result": result}

    # Explicit success signals
    if result.get("ok") is True or result.get("success") is True:
        return {"ok": True, "action": action, "result": result}
    if str(result.get("status") or "").lower() in {
        "ok",
        "success",
        "succeeded",
        "claimed",
        "accepted",
        "submitted",
        "delivered",
        "pending",
        "open",
    }:
        return {"ok": True, "action": action, "result": result}

    # Known resource ids often returned after claim/submit
    if any(result.get(k) for k in ("claim_id", "submission_id", "delivery_id", "job_id", "task_id", "id")):
        return {"ok": True, "action": action, "result": result, "inferred": "resource_id"}

    return {
        "ok": False,
        "error": "ambiguous_platform_response",
        "action": action,
        "hint": "Platform response lacked an explicit success field; refusing to treat as success.",
        "result": result,
    }
