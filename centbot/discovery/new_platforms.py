"""Discover additional paid-task sources — probe real URLs, never invent catalogs.

When ``discovery.auto_discover_platforms`` is true, CENTBOT probes a curated list of
known public boards and appends reachable ones under ``platforms.extra`` in local.yaml.
"""

from __future__ import annotations

from typing import Any

import yaml

from centbot.core.config import Config
from centbot.runtime_paths import install_root
from centbot.platforms.http import HttpClient, PlatformHTTPError
from centbot.platforms.registry import ExtraRewardSource, build_platforms

# Curated public candidates (real hosts only). Empty list results are kept as notes.
KNOWN_CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "algora_bounties",
        "base_url": "https://algora.io",
        "list_path": "/api/bounties",
        "enabled": True,
    },
    {
        "name": "gitcoin_grants",
        "base_url": "https://api.scorer.gitcoin.co",
        "list_path": "/",
        "enabled": True,
    },
]


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


def probe_url(url: str, *, path: str = "/", timeout: float = 15.0) -> dict[str, Any]:
    """Low-level reachability check for a candidate API root (no task invention)."""
    try:
        client = HttpClient(url.rstrip("/"), timeout=timeout)
        data = client.get_json(path if path.startswith("/") else f"/{path}")
        return {"ok": True, "url": url, "path": path, "payload_type": type(data).__name__}
    except PlatformHTTPError as exc:
        return {"ok": False, "url": url, "path": path, "error": str(exc), "status": exc.status}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "path": path, "error": str(exc)}


def discover_candidate_platforms(config: Config) -> list[dict[str, Any]]:
    """Probe known public boards; return honest reachability (may be empty/unreachable)."""
    reports: list[dict[str, Any]] = []
    existing = {str(x.get("name")) for x in (config.get("platforms.extra") or []) if isinstance(x, dict)}
    builtin = set((config.section("platforms") or {}).keys()) - {"extra"}
    for cand in KNOWN_CANDIDATES:
        name = str(cand["name"])
        if name in existing or name in builtin:
            reports.append({"ok": True, "name": name, "skipped": True, "reason": "already_configured"})
            continue
        probe = probe_url(str(cand["base_url"]), path=str(cand.get("list_path") or "/"))
        reports.append({**probe, "name": name, "candidate": cand})
    return reports


def auto_attach_reachable(config: Config, *, persist: bool = True) -> dict[str, Any]:
    """If auto_discover enabled, append reachable new candidates to platforms.extra."""
    if not bool(config.get("discovery.auto_discover_platforms", True)):
        return {"ok": True, "skipped": True, "reason": "auto_discover_disabled"}
    found = discover_candidate_platforms(config)
    attached: list[str] = []
    extras = list(config.get("platforms.extra") or [])
    if not isinstance(extras, list):
        extras = []
    for row in found:
        if row.get("skipped") or not row.get("ok"):
            continue
        cand = row.get("candidate") or {}
        if not cand.get("name") or not cand.get("base_url"):
            continue
        extras.append(
            {
                "name": cand["name"],
                "enabled": True,
                "base_url": cand["base_url"],
                "list_path": cand.get("list_path") or "/",
            }
        )
        attached.append(str(cand["name"]))
    if attached and persist:
        local_path = install_root() / "config" / "local.yaml"
        existing: dict[str, Any] = {}
        if local_path.exists():
            existing = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        platforms = dict(existing.get("platforms") or {})
        platforms["extra"] = extras
        existing["platforms"] = platforms
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(yaml.safe_dump(existing, sort_keys=False, allow_unicode=True), encoding="utf-8")
        config.set("platforms.extra", extras)
    return {"ok": True, "probed": len(found), "attached": attached, "reports": found}


def list_active_connectors(config: Config) -> dict[str, Any]:
    platforms = build_platforms(config)
    return {
        name: {
            "enabled": bool(getattr(conn, "enabled", True)),
            "class": type(conn).__name__,
        }
        for name, conn in platforms.items()
    }
