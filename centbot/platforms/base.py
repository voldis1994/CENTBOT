"""Base platform connector."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class PlatformTask:
    platform: str
    external_id: str
    title: str
    description: str = ""
    reward_amount: float = 0.0
    reward_currency: str = "USD"
    url: str = ""
    category_hint: str = ""
    payer_id: str = ""
    payer_rating: float | None = None
    funded: bool = False
    available: bool = True
    automation_allowed: bool | None = None
    claimable: bool = True
    payment_state: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["raw_json"] = d.pop("raw")
        return d


class PlatformConnector(ABC):
    name: str = "base"

    def __init__(self, config: dict[str, Any], api_key: str = ""):
        self.config = config
        self.api_key = api_key
        self.enabled = bool(config.get("enabled", True))

    @abstractmethod
    def list_tasks(self) -> list[PlatformTask]:
        ...

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Use official API only. Respect platform ToS.",
            "requires_human_review": False,
        }

    def check_availability(self, task: PlatformTask) -> bool:
        return task.available and task.claimable

    def check_funding(self, task: PlatformTask) -> bool:
        return task.funded

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name}: accept not implemented / credentials required")

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name}: submit not implemented / credentials required")

    def check_submission_status(self, submission_id: str) -> dict[str, Any]:
        return {"submission_id": submission_id, "status": "unknown"}

    def check_payment(self, task_id: str) -> dict[str, Any]:
        return {"task_id": task_id, "status": "unknown"}

    def register_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Honest default: platform has no automated registration in CENTBOT."""
        return {
            "ok": False,
            "error": "register_api_unsupported",
            "platform": self.name,
            "status": "error",
            "user_action": "register_manually_on_platform_then_store_api_credentials",
            "hint": f"{self.name} does not expose an approved auto-register endpoint to CENTBOT",
        }

    def health(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "enabled": self.enabled,
            "configured": bool(self.api_key or self.config.get("base_url")),
            "base_url": self.config.get("base_url") or None,
            "live": True,
        }
