"""Rebuild PlatformTask objects from stored DB rows."""

from __future__ import annotations

import json
from typing import Any

from centbot.platforms.base import PlatformTask


def task_from_row(row: dict[str, Any]) -> PlatformTask:
    raw = row.get("raw_json") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {"raw": raw}
    return PlatformTask(
        platform=str(row.get("platform") or ""),
        external_id=str(row.get("external_id") or ""),
        title=str(row.get("title") or ""),
        description=str(row.get("description") or ""),
        reward_amount=float(row.get("reward_amount") or 0),
        reward_currency=str(row.get("reward_currency") or "USD"),
        url=str((raw or {}).get("origin_url") or (raw or {}).get("url") or ""),
        category_hint=str(row.get("category") or ""),
        payer_id="",
        payer_rating=float(row.get("payer_trust") or 0.5),
        funded=bool(row.get("funded")),
        available=bool(row.get("available")),
        claimable=(
            False
            if str(row.get("platform") or "") in {"jobbi", "agentizable"}
            else bool(row.get("claimable", row.get("available")))
        ),
        automation_allowed=True,
        payment_state=str((raw or {}).get("jobbi", {}).get("payment_state") or ""),
        raw=dict(raw or {}),
    )
