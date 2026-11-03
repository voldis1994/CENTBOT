"""Global paid-task scanner across platforms."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from centbot.core.database import Database
from centbot.core.logger import ActionJournal, get_logger
from centbot.platforms.base import PlatformConnector, PlatformTask

log = get_logger("centbot.discovery")


def fingerprint(task: PlatformTask) -> str:
    blob = f"{task.platform}|{task.title.strip().lower()}|{task.reward_amount}|{task.reward_currency}"
    return hashlib.sha256(blob.encode()).hexdigest()


class GlobalTaskScanner:
    def __init__(self, platforms: dict[str, PlatformConnector], db: Database, journal: ActionJournal):
        self.platforms = platforms
        self.db = db
        self.journal = journal
        self._seen_external: set[str] = set()

    def scan(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for name, conn in self.platforms.items():
            if not conn.enabled:
                continue
            # Skip platforms auto-stopped for unprofitability
            stats = self.db.fetchone("SELECT enabled FROM platform_stats WHERE platform=?", (name,))
            if stats and not stats["enabled"]:
                continue
            try:
                tasks = conn.list_tasks()
            except Exception as exc:  # noqa: BLE001
                log.error("Scan failed for %s: %s", name, exc)
                self.journal.record("scan", "error", platform=name, error=str(exc))
                continue
            for t in tasks:
                key = f"{t.platform}:{t.external_id}"
                is_new = key not in self._seen_external
                self._seen_external.add(key)
                row = {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                    "platform": t.platform,
                    "external_id": t.external_id,
                    "title": t.title,
                    "description": t.description,
                    "reward_amount": t.reward_amount,
                    "reward_currency": t.reward_currency,
                    "category": t.category_hint or None,
                    "funded": 1 if t.funded else 0,
                    "available": 1 if t.available else 0,
                    "claimable": 1 if t.claimable else 0,
                    "payer_trust": t.payer_rating if t.payer_rating is not None else 0.5,
                    "fingerprint": fingerprint(t),
                    "status": "discovered",
                    "raw_json": t.raw,
                    "automation_allowed": t.automation_allowed,
                    "is_new": is_new,
                    "_task": t,
                }
                found.append(row)
        self.journal.record("scan", "ok", count=len(found))
        return found
