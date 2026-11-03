"""Jobbi live gig index connector — https://jobbi.org/gigs.json"""

from __future__ import annotations

from typing import Any

from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.http import HttpClient, PlatformHTTPError

GRADE_TRUST = {
    "A+": 0.98,
    "A": 0.95,
    "A-": 0.9,
    "B+": 0.85,
    "B": 0.8,
    "B-": 0.75,
    "C+": 0.65,
    "C": 0.55,
    "C-": 0.45,
    "D": 0.3,
    "F": 0.15,
}


class JobbiConnector(PlatformConnector):
    name = "jobbi"

    def __init__(self, config: dict[str, Any], api_key: str = ""):
        super().__init__(config, api_key)
        base = (config.get("base_url") or "https://jobbi.org").rstrip("/")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 30)))
        self.min_reward = float(config.get("min_reward", 0) or 0)
        self.lane = str(config.get("lane", "agent"))
        self.limit = int(config.get("limit", 100))
        self.currency = config.get("currency")
        self.source = config.get("source")
        self.query = config.get("query")

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"lane": self.lane, "limit": self.limit}
        if self.min_reward:
            params["min_reward"] = self.min_reward
        if self.currency:
            params["currency"] = self.currency
        if self.source:
            params["source"] = self.source
        if self.query:
            params["q"] = self.query
        if self.config.get("operator"):
            params["operator"] = self.config["operator"]
        data = self.client.get_json("/gigs.json", params=params, use_etag=True)
        if not data or data.get("_not_modified"):
            return []
        items = data.get("items") or []
        out: list[PlatformTask] = []
        for item in items:
            meta = item.get("_jobbi") or {}
            reward = meta.get("reward") or {}
            amount = reward.get("amount")
            if amount is None:
                amount = 0.0
            try:
                amount_f = float(amount)
            except (TypeError, ValueError):
                amount_f = 0.0
            if self.min_reward and amount_f < self.min_reward:
                continue
            grade = str(meta.get("payout_grade") or "C")
            payment_state = str(meta.get("payment_state") or "unknown")
            funded = payment_state in {"escrowed", "funded"}
            claims_open = meta.get("claims_open")
            available = True if claims_open is None else bool(claims_open)
            out.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(item.get("id")),
                    title=str(item.get("title") or "Untitled gig"),
                    description=str(item.get("content_text") or ""),
                    reward_amount=amount_f,
                    reward_currency=str(reward.get("currency") or "USD"),
                    url=str(item.get("url") or ""),
                    category_hint=_hint_from_tags(item.get("tags") or []),
                    payer_id=str(meta.get("source") or ""),
                    payer_rating=GRADE_TRUST.get(grade, GRADE_TRUST.get(grade[:1], 0.5)),
                    funded=funded,
                    available=available,
                    # Jobbi is an index only — never auto-claimable in CENTBOT
                    claimable=False,
                    automation_allowed=True,
                    payment_state=payment_state,
                    raw={
                        "source": "jobbi",
                        "jobbi": meta,
                        "tags": item.get("tags"),
                        "date_published": item.get("date_published"),
                        "origin_source": meta.get("source"),
                        "origin_url": item.get("url"),
                    },
                )
            )
        return out

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Jobbi is a read-only index. Claim/submit on the originating board URL.",
            "requires_human_review": True,
            "poll_etiquette": "At most hourly; use ETag/If-None-Match.",
        }

    def register_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "index_only_no_accounts",
            "platform": self.name,
            "status": "error",
            "user_action": "register_on_originating_board_then_configure_that_connector",
            "hint": "Jobbi is a read-only gig index — it has no accounts or payouts",
        }

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        # Jobbi cannot claim; return handoff to originating board.
        return {
            "ok": False,
            "reason": "index_only",
            "handoff_url": task.url,
            "origin_source": (task.raw or {}).get("origin_source"),
            "message": "Open the originating board to claim; Jobbi does not hold claims or pay.",
        }

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "reason": "index_only",
            "handoff_url": task.url,
            "payload_keys": list(payload.keys()),
        }

    def health(self) -> dict[str, Any]:
        try:
            data = self.client.get_json("/gigs.json", params={"lane": self.lane, "limit": 1})
            count = len((data or {}).get("items") or [])
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": True,
                "sample_ok": count >= 0,
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


def _hint_from_tags(tags: list[Any]) -> str:
    joined = " ".join(str(t).lower() for t in tags)
    mapping = [
        ("code", "programming"),
        ("python", "programming"),
        ("csv", "csv"),
        ("excel", "excel"),
        ("pdf", "pdf"),
        ("image", "image"),
        ("writing", "text"),
        ("content", "text"),
        ("data", "json_xml"),
        ("android", "android"),
        ("browser", "browser"),
    ]
    for needle, cat in mapping:
        if needle in joined:
            return cat
    return "other"
