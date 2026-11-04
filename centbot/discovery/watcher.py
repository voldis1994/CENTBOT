"""Automatic new-task detection — distinguish new / known / reavailable / completed."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database
from centbot.core.logger import ActionJournal

_DONE = {"completed", "paid", "submitted", "verified", "dry_run_completed", "rejected", "skipped"}
_REOPENABLE = {"failed", "submit_failed", "needs_repair", "eligible", "accepted", "dry_run_accepted"}


class NewTaskWatcher:
    def __init__(self, db: Database, journal: ActionJournal):
        self.db = db
        self.journal = journal

    def detect_new(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Classify candidates; only brand-new rows enter analysis as is_new.

        Sets discovery_state on each task:
        - new: never seen
        - known: previously stored, still open-ish
        - reavailable: was failed/repair and listing is open again
        - completed: already finished / paid / submitted — do not re-accept
        """
        new_ones: list[dict[str, Any]] = []
        known = reavailable = completed = 0
        for task in candidates:
            existing = self.db.fetchone(
                "SELECT id, status FROM tasks WHERE platform=? AND external_id=?",
                (task["platform"], task["external_id"]),
            )
            if existing is None:
                task["is_new"] = True
                task["discovery_state"] = "new"
                new_ones.append(task)
                continue
            status = str(existing.get("status") or "")
            task["is_new"] = False
            task["id"] = existing["id"]
            task["prior_status"] = status
            if status in _DONE:
                task["discovery_state"] = "completed"
                completed += 1
            elif status in _REOPENABLE and bool(task.get("available", True)):
                task["discovery_state"] = "reavailable"
                reavailable += 1
                # Soft re-queue only failed lanes — never auto-flip submitted/paid
                if status in {"failed", "submit_failed", "needs_repair"} and task.get("available"):
                    # Mark for operator visibility; schedule_eligible still gates accepts
                    task["requeue_candidate"] = True
            else:
                task["discovery_state"] = "known"
                known += 1
        if new_ones or known or reavailable or completed:
            self.journal.record(
                "new_tasks",
                "ok",
                count=len(new_ones),
                known=known,
                reavailable=reavailable,
                completed=completed,
            )
        return new_ones
