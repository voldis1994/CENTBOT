"""Discover additional paid-task sources from configuration — never invent platforms.

New boards must be declared under ``platforms.extra`` with a real ``base_url``.
CENTBOT will probe them and report reachability; it will not fabricate catalogs.
"""

from __future__ import annotations

from typing import Any

from centbot.core.config import Config
from centbot.platforms.http import HttpClient, PlatformHTTPError
from centbot.platforms.registry import ExtraRewardSource, build_platforms


def scout_configured_extras(config: Config) -> list[dict[str, Any]]:
    """Probe each configured extra source; return honest reachability reports."""
    extras = config.get("platforms.extra", []) or []
    reports: list[dict[str, Any]] = []
    for item in extras:
        if not isinstance(item, dict) or not item.get("name") or not item.get("base_url"):
            reports.append({"ok": False, "error": "invalid_extra_config", "item": item})
            continue
        name = str(item["name"])
        try:
            conn = ExtraRewardSource(name, item, api_key=config.env(item.get("api_key_env", "")))
            tasks = conn.list_tasks()
            reports.append(
                {
                    "ok": True,
                    "name": name,
                    "base_url": item.get("base_url"),
                    "task_count": len(tasks),
                    "note": None if tasks else "reachable_but_empty",
                }
            )
        except Exception as exc:  # noqa: BLE001
            reports.append({"ok": False, "name": name, "error": str(exc), "base_url": item.get("base_url")})
    return reports


def probe_url(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """Low-level reachability check for a candidate API root (no task invention)."""
    try:
        client = HttpClient(url.rstrip("/"), timeout=timeout)
        data = client.get_json("/")
        return {"ok": True, "url": url, "payload_type": type(data).__name__}
    except PlatformHTTPError as exc:
        return {"ok": False, "url": url, "error": str(exc), "status": exc.status}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "error": str(exc)}


def list_active_connectors(config: Config) -> dict[str, Any]:
    platforms = build_platforms(config)
    return {
        name: {
            "enabled": bool(getattr(conn, "enabled", True)),
            "class": type(conn).__name__,
        }
        for name, conn in platforms.items()
    }
