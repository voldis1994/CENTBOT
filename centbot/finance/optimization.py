"""Profit optimization and unprofitable platform stopping."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database, utcnow
from centbot.core.logger import ActionJournal
from centbot.finance.ledger import FinanceLedger


class ProfitOptimizer:
    def __init__(self, db: Database, ledger: FinanceLedger, journal: ActionJournal, config: dict[str, Any]):
        self.db = db
        self.ledger = ledger
        self.journal = journal
        self.config = config

    def stop_unprofitable(self) -> list[str]:
        stopped: list[str] = []
        threshold = int(self.config.get("stop_platform_after_losses", 3))
        rows = self.db.fetchall("SELECT * FROM platform_stats")
        for row in rows:
            if int(row.get("losses_streak") or 0) >= threshold and row.get("enabled", 1):
                self.db.execute(
                    "UPDATE platform_stats SET enabled=0, updated_at=? WHERE platform=?",
                    (utcnow(), row["platform"]),
                )
                stopped.append(row["platform"])
                self.journal.record("platform_stop", "unprofitable", platform=row["platform"])
                self.db.add_alert("warning", f"Platform stopped: {row['platform']}", source="optimizer")
        return stopped

    def rebalance_priorities(self) -> dict[str, float]:
        """Return platform weight multipliers based on historical profit."""
        stats = self.ledger.platform_profitability()
        weights: dict[str, float] = {}
        for row in stats:
            profit = float(row.get("profit") or 0)
            weights[row["platform"]] = max(0.2, min(2.0, 1.0 + profit / 100.0))
        self.db.set_state("platform_weights", weights)
        self.journal.record("optimize", "rebalance", weights=weights)
        return weights

    def learn_from_reward(self, platform: str, success: bool, amount_base: float = 0.0) -> None:
        if success:
            self.ledger.update_platform_stats(platform, paid=1, revenue_base=amount_base, losses_streak=-999)
            # reset streak properly
            self.db.execute("UPDATE platform_stats SET losses_streak=0, updated_at=? WHERE platform=?", (utcnow(), platform))
        else:
            row = self.db.fetchone("SELECT losses_streak FROM platform_stats WHERE platform=?", (platform,))
            streak = int(row["losses_streak"]) + 1 if row else 1
            if not row:
                self.db.execute("INSERT INTO platform_stats(platform, losses_streak, updated_at) VALUES(?,?,?)", (platform, streak, utcnow()))
            else:
                self.db.execute("UPDATE platform_stats SET losses_streak=?, updated_at=? WHERE platform=?", (streak, utcnow(), platform))
        self.stop_unprofitable()
