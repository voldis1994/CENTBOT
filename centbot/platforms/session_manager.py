"""Unified platform account registration, authorization, and session manager.

Never prints private keys. CAPTCHA / KYC / 2FA / payment confirmation → user handoff.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from centbot.core.logger import get_logger
from centbot.runtime_paths import install_root

log = get_logger("centbot.sessions")

# Platforms that may auto-register without human gates
AUTO_REGISTER_OK = {"basedagents", "taskmarket"}
# Always require explicit user confirmation
USER_CONFIRM_REQUIRED = {"agentizable", "bountybook", "jobbi"}


def _sessions_path() -> Path:
    return install_root() / "data" / "platforms" / "sessions.json"


class PlatformSessionManager:
    def __init__(
        self,
        platforms: dict[str, Any],
        *,
        credential_getter: Callable[[str], Any] | None = None,
        journal: Any | None = None,
    ):
        self.platforms = platforms
        self.credential_getter = credential_getter
        self.journal = journal
        self._unreachable: dict[str, float] = {}  # platform -> backoff_until
        self._path = _sessions_path()

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"sessions": {}, "updated_at": None}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"sessions": {}, "updated_at": None}

    def save(self, data: dict[str, Any]) -> Path:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = time.time()
        # Never persist private keys
        safe = json.loads(json.dumps(data, default=str))
        for name, sess in (safe.get("sessions") or {}).items():
            for bad in ("private_key", "secret", "mnemonic", "raw_key"):
                if bad in sess:
                    sess[bad] = "[redacted]"
        self._path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        return self._path

    def mark_unreachable(self, platform: str, *, backoff_s: float = 3600.0, error: str = "") -> None:
        self._unreachable[platform] = time.time() + backoff_s
        data = self.load()
        sess = data.setdefault("sessions", {}).setdefault(platform, {})
        sess["unreachable"] = True
        sess["error"] = str(error)[:500]
        sess["backoff_until"] = self._unreachable[platform]
        self.save(data)
        log.warning("platform unreachable (backoff %.0fs): %s — %s", backoff_s, platform, error[:120])

    def is_in_backoff(self, platform: str) -> bool:
        until = self._unreachable.get(platform) or 0
        if until and time.time() < until:
            return True
        data = self.load()
        sess = (data.get("sessions") or {}).get(platform) or {}
        until2 = float(sess.get("backoff_until") or 0)
        return bool(until2 and time.time() < until2)

    def refresh_all(self, *, auto_register_allowed: bool = True) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for name, conn in self.platforms.items():
            if self.is_in_backoff(name):
                results[name] = {"ok": False, "skipped": True, "reason": "backoff"}
                continue
            try:
                results[name] = self.ensure_session(name, conn, auto_register_allowed=auto_register_allowed)
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                if _looks_dns(err):
                    self.mark_unreachable(name, error=err)
                results[name] = {"ok": False, "error": err}
        return results

    def ensure_session(self, name: str, conn: Any, *, auto_register_allowed: bool = True) -> dict[str, Any]:
        data = self.load()
        sess = data.setdefault("sessions", {}).setdefault(name, {})
        # Health probe
        try:
            health = conn.health() if hasattr(conn, "health") else {"ok": True}
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            if _looks_dns(err):
                self.mark_unreachable(name, error=err)
                return {"ok": False, "error": "platform_offline_dns", "platform": name}
            return {"ok": False, "error": err, "platform": name}

        if health.get("live") is False and _looks_dns(str(health.get("error") or "")):
            self.mark_unreachable(name, error=str(health.get("error")))
            return {"ok": False, "error": "platform_offline_dns", "platform": name, "health": health}

        # Auth refresh paths
        if name == "taskmarket":
            out = self._taskmarket_auth(conn, sess)
        elif name == "basedagents":
            out = self._basedagents_auth(conn, sess, auto_register_allowed=auto_register_allowed)
        elif name == "agentizable":
            out = self._agentizable_auth(conn, sess)
        elif name == "jobbi":
            out = self._jobbi_auth(conn, sess)
        elif name == "bountybook":
            out = self._bountybook_auth(conn, sess, health)
        else:
            out = {"ok": bool(health.get("live", True)), "platform": name, "health": health}

        sess.update({k: v for k, v in out.items() if k not in {"private_key", "secret"}})
        sess["refreshed_at"] = time.time()
        self.save(data)
        if self.journal:
            # Never journal secrets
            safe = {k: v for k, v in out.items() if "key" not in k.lower() and "secret" not in k.lower()}
            self.journal.record("session", "ok" if out.get("ok") else "warn", platform=name, **safe)
        return out

    def _taskmarket_auth(self, conn: Any, sess: dict[str, Any]) -> dict[str, Any]:
        # Ethereum wallet signature only — no separate API key
        if not getattr(conn, "wallet", None):
            return {
                "ok": False,
                "platform": "taskmarket",
                "error": "wallet_required",
                "user_action": "SET_ETH_KEY.bat",
            }
        try:
            reg = conn.register_account({})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "platform": "taskmarket", "error": str(exc)}
        return {
            "ok": bool(reg.get("ok")),
            "platform": "taskmarket",
            "auth": "eip191_wallet",
            "worker_address": getattr(conn.wallet, "address", None),
            "status": reg.get("status"),
            "error": reg.get("error"),
        }

    def _basedagents_auth(self, conn: Any, sess: dict[str, Any], *, auto_register_allowed: bool) -> dict[str, Any]:
        if not auto_register_allowed and not sess.get("registered"):
            return {"ok": False, "platform": "basedagents", "error": "auto_register_disabled", "user_action": "REGISTER_BASED.bat"}
        try:
            if hasattr(conn, "ensure_identity"):
                result = conn.ensure_identity()
            elif hasattr(conn, "register_account"):
                result = conn.register_account({})
            else:
                result = {"ok": True, "status": "present"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "platform": "basedagents", "error": str(exc)}
        return {
            "ok": bool(result.get("ok")),
            "platform": "basedagents",
            "auth": "agentsig",
            "registered": bool(result.get("ok")),
            "status": result.get("status"),
            "error": result.get("error"),
            "agent_id": result.get("agent_id") or result.get("id"),
        }

    def _agentizable_auth(self, conn: Any, sess: dict[str, Any]) -> dict[str, Any]:
        # Requires user confirmation — never silent claim
        if not sess.get("user_confirmed"):
            try:
                reg = conn.register_account({}) if hasattr(conn, "register_account") else {}
            except Exception as exc:  # noqa: BLE001
                reg = {"ok": False, "error": str(exc)}
            return {
                "ok": False,
                "platform": "agentizable",
                "error": "human_authorization_required",
                "user_action": "Open Agentizable, confirm wallet, then mark session user_confirmed",
                "status": "needs_user",
                "register": {k: v for k, v in (reg or {}).items() if "key" not in str(k).lower()},
            }
        return {"ok": True, "platform": "agentizable", "auth": "user_confirmed", "status": "authorized"}

    def _jobbi_auth(self, conn: Any, sess: dict[str, Any]) -> dict[str, Any]:
        # Jobbi is an index — hand off to origin platforms with real integrations
        return {
            "ok": True,
            "platform": "jobbi",
            "auth": "index_only",
            "note": "Jobbi listings route to origin platforms (BasedAgents/TaskMarket/…) — no direct claim",
            "handoff": True,
        }

    def _bountybook_auth(self, conn: Any, sess: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
        err = str(health.get("error") or "")
        if _looks_dns(err):
            self.mark_unreachable("bountybook", error=err)
            return {"ok": False, "platform": "bountybook", "error": "platform_offline_dns"}
        return {
            "ok": bool(health.get("live")),
            "platform": "bountybook",
            "auth": "bearer_or_wallet",
            "status": "reachable" if health.get("live") else "unreachable",
            "error": health.get("error"),
            "user_action": "CAPTCHA/KYC/2FA must be completed by the user in the browser if required",
        }


def _looks_dns(err: str) -> bool:
    lower = (err or "").lower()
    return any(
        x in lower
        for x in (
            "name or service not known",
            "nodename nor servname",
            "getaddrinfo failed",
            "failed to resolve",
            "nxdomain",
            "11001",
            "platform_offline_dns",
            "dns",
        )
    )
