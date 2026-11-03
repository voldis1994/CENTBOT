"""Automatic platform registration — only when allowed + user permission.

Never bypass CAPTCHA/KYC/2FA. Failures are recorded as errors, not success.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from centbot.core.config import Config, ROOT
from centbot.core.logger import ActionJournal, get_logger
from centbot.discovery.new_platforms import scout_configured_extras
from centbot.windows.secrets import SecretStore

log = get_logger("centbot.registration")

REGISTRY_PATH = ROOT / "data" / "platforms" / "accounts.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else REGISTRY_PATH
    if not path.exists():
        return {"accounts": {}, "updated_at": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"accounts": {}, "updated_at": None}


def save_registry(data: dict[str, Any], path: Path | None = None) -> Path:
    path = Path(path) if path else REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _utcnow()
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def assess_platform(name: str, info: dict[str, Any]) -> dict[str, Any]:
    """Trust / automation / payment assessment from integration probe."""
    automation = info.get("automation") or {}
    ok = bool(info.get("ok"))
    allowed = automation.get("automation_allowed")
    human = bool(automation.get("requires_human_review"))
    return {
        "platform": name,
        "reachable": ok,
        "automation_allowed": bool(allowed) if allowed is not None else False,
        "requires_human_review": human,
        "payment_notes": automation.get("notes") or info.get("note"),
        "trust": "probe_only",  # no invented reputation scores
        "registerable": bool(ok and allowed and not human),
    }


def attempt_register(
    platform: str,
    *,
    config: Config,
    journal: ActionJournal | None = None,
    operator: dict[str, Any] | None = None,
    secrets: SecretStore | None = None,
    registry_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Register only if discovery.auto_register_allowed and platform permits automation."""
    auto = bool(config.get("discovery.auto_register_allowed") or config.get("platforms.auto_register"))
    if not auto and not force:
        return {"ok": False, "error": "auto_register_disabled", "platform": platform, "status": "blocked"}

    from centbot.platforms.registry import verify_integrations, build_platforms

    platforms = build_platforms(config)
    integrations = verify_integrations(platforms)
    info = integrations.get(platform) or {}
    assessment = assess_platform(platform, info)
    if not assessment["reachable"]:
        out = {"ok": False, "error": "platform_unreachable", "status": "error", **assessment}
        _record(registry_path, platform, out)
        if journal:
            journal.record("platform_register", "error", platform=platform, error=out["error"])
        return out
    if not assessment["automation_allowed"]:
        out = {
            "ok": False,
            "error": "automation_not_allowed",
            "status": "needs_user",
            "user_action": "manual_registration_or_policy_review",
            **assessment,
        }
        _record(registry_path, platform, out)
        if journal:
            journal.record("platform_register", "needs_user", platform=platform)
        return out
    if assessment["requires_human_review"]:
        out = {
            "ok": False,
            "error": "requires_human_review",
            "status": "needs_user",
            "user_action": "complete_KYC_2FA_CAPTCHA_or_email_verification_on_platform",
            **assessment,
        }
        _record(registry_path, platform, out)
        if journal:
            journal.record("platform_register", "needs_user", platform=platform, reason="human_review")
        return out

    conn = platforms.get(platform)
    if not conn or not hasattr(conn, "register_account"):
        out = {
            "ok": False,
            "error": "register_api_unsupported",
            "status": "error",
            "hint": "Platform has no approved automated registration endpoint in CENTBOT",
            **assessment,
        }
        _record(registry_path, platform, out)
        if journal:
            journal.record("platform_register", "error", platform=platform, error=out["error"])
        return out

    operator = operator or config.section("operator")
    payload = {
        "name": operator.get("full_name"),
        "email": operator.get("email"),
        "country": operator.get("country"),
        "phone": operator.get("phone"),
        # payouts: public details only
        "iban": config.get("finance.bank_iban"),
        "crypto_wallet": config.get("finance.crypto_wallet_public"),
    }
    try:
        result = conn.register_account(payload)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": str(exc), "status": "error", **assessment}
        _record(registry_path, platform, out)
        if journal:
            journal.record("platform_register", "error", platform=platform, error=str(exc))
        return out

    if not isinstance(result, dict) or not result.get("ok"):
        out = {
            "ok": False,
            "error": (result or {}).get("error") if isinstance(result, dict) else "register_failed",
            "status": "error",
            "result": result,
            **assessment,
        }
        _record(registry_path, platform, out)
        if journal:
            journal.record("platform_register", "error", platform=platform, result=result)
        return out

    # Store tokens securely if returned (never seed/password)
    if secrets and result.get("api_token"):
        secrets.set(f"{platform}_api_token", str(result["api_token"]))
    out = {"ok": True, "status": "registered", "platform": platform, "result": {k: v for k, v in result.items() if k != "api_token"}}
    _record(registry_path, platform, out)
    if journal:
        journal.record("platform_register", "ok", platform=platform)
    return out


def _record(path: Path | None, platform: str, entry: dict[str, Any]) -> None:
    reg = load_registry(path)
    accounts = reg.setdefault("accounts", {})
    accounts[platform] = {
        "status": entry.get("status"),
        "ok": entry.get("ok"),
        "error": entry.get("error"),
        "user_action": entry.get("user_action"),
        "updated_at": _utcnow(),
    }
    save_registry(reg, path)


def registration_status(path: Path | None = None) -> dict[str, Any]:
    return load_registry(path)


def scout_and_assess(config: Config) -> list[dict[str, Any]]:
    extras = scout_configured_extras(config)
    from centbot.platforms.registry import verify_integrations, build_platforms

    integrations = verify_integrations(build_platforms(config))
    reports = [assess_platform(n, info) for n, info in integrations.items()]
    for ex in extras:
        reports.append(
            {
                "platform": ex.get("name") or "extra",
                "reachable": bool(ex.get("ok")),
                "automation_allowed": False,
                "requires_human_review": True,
                "trust": "extra_configured",
                "registerable": False,
                "note": ex.get("error") or ex.get("note"),
            }
        )
    return reports
