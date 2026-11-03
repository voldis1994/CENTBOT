"""Submitted work status checks."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database, utcnow


class SubmissionStatusChecker:
    def __init__(self, platforms: dict, db: Database):
        self.platforms = platforms
        self.db = db

    def poll_pending(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM submissions WHERE status IN ('submitted', 'dry_run_submitted', 'pending') ORDER BY id DESC LIMIT 50"
        )
        updates = []
        for row in rows:
            conn = self.platforms.get(row["platform"])
            if not conn:
                continue
            # Demo: dry_run submissions auto-approve
            if row["status"] == "dry_run_submitted":
                status = "approved"
            else:
                status = conn.check_submission_status(str(row["id"])).get("status", "unknown")
            self.db.execute(
                "UPDATE submissions SET status=?, checked_at=? WHERE id=?",
                (status, utcnow(), row["id"]),
            )
            updates.append({**row, "status": status})
        return updates
