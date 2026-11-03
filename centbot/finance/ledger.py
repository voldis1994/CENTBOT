"""Bank/crypto rewards, fees, profit, double-entry prevention, withdrawals, stats."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database, utcnow
from centbot.core.logger import ActionJournal
from centbot.finance.currency import to_base


class FinanceLedger:
    def __init__(self, db: Database, journal: ActionJournal, default_currency: str = "USD", wallet_public: str = ""):
        self.db = db
        self.journal = journal
        self.default_currency = default_currency
        self.wallet_public = wallet_public

    def record_bank_reward(self, *, amount: float, currency: str, platform: str, task_id: str | None = None, tx_ref: str) -> bool:
        ok = self.db.record_income(
            kind="bank",
            amount=amount,
            currency=currency,
            platform=platform,
            task_id=task_id,
            amount_base=to_base(amount, currency, self.default_currency),
            tx_ref=tx_ref,
            status="received",
        )
        self.journal.record("income_bank", "ok" if ok else "duplicate", tx_ref=tx_ref, amount=amount, currency=currency)
        return ok

    def record_crypto_reward(self, *, amount: float, currency: str, platform: str, task_id: str | None = None, tx_ref: str) -> bool:
        ok = self.db.record_income(
            kind="crypto",
            amount=amount,
            currency=currency,
            platform=platform,
            task_id=task_id,
            amount_base=to_base(amount, currency, self.default_currency),
            tx_ref=tx_ref,
            status="received",
            notes=f"wallet:{self.wallet_public}" if self.wallet_public else "",
        )
        self.journal.record("income_crypto", "ok" if ok else "duplicate", tx_ref=tx_ref, amount=amount, currency=currency)
        return ok

    def record_fee(self, *, amount: float, currency: str, platform: str | None = None, tx_ref: str, notes: str = "") -> bool:
        return self.db.record_income(
            kind="fee",
            amount=-abs(amount),
            currency=currency,
            platform=platform,
            amount_base=-abs(to_base(amount, currency, self.default_currency)),
            tx_ref=tx_ref,
            status="recorded",
            notes=notes,
        )

    def record_expense(self, *, amount: float, currency: str, tx_ref: str, notes: str = "") -> bool:
        return self.db.record_income(
            kind="expense",
            amount=-abs(amount),
            currency=currency,
            amount_base=-abs(to_base(amount, currency, self.default_currency)),
            tx_ref=tx_ref,
            status="recorded",
            notes=notes,
        )

    def total_profit(self) -> float:
        row = self.db.fetchone("SELECT COALESCE(SUM(amount_base),0) AS total FROM income WHERE status IN ('recorded','received','approved')")
        return float(row["total"] if row else 0)

    def income_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.fetchall("SELECT * FROM income ORDER BY id DESC LIMIT ?", (limit,))

    def request_withdrawal(self, amount: float, currency: str, destination: str, notes: str = "") -> int:
        return self.db.execute(
            "INSERT INTO withdrawals(amount, currency, destination, status, requested_at, notes) VALUES(?,?,?,?,?,?)",
            (amount, currency, destination, "pending_approval", utcnow(), notes),
        )

    def approve_withdrawal(self, withdrawal_id: int) -> bool:
        row = self.db.fetchone("SELECT * FROM withdrawals WHERE id=?", (withdrawal_id,))
        if not row or row["status"] != "pending_approval":
            return False
        self.db.execute(
            "UPDATE withdrawals SET status=?, approved_at=? WHERE id=?",
            ("approved", utcnow(), withdrawal_id),
        )
        self.db.record_income(
            kind="withdrawal",
            amount=-abs(float(row["amount"])),
            currency=row["currency"],
            amount_base=-abs(to_base(float(row["amount"]), row["currency"], self.default_currency)),
            tx_ref=f"withdrawal-{withdrawal_id}",
            status="approved",
            notes=row.get("destination") or "",
        )
        self.journal.record("withdrawal", "approved", id=withdrawal_id)
        return True

    def verify_payment_received(self, tx_ref: str) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM income WHERE tx_ref=?", (tx_ref,))
        if not row:
            return {"ok": False, "status": "not_found"}
        return {"ok": row["status"] in ("received", "approved", "recorded"), "row": row}

    def platform_profitability(self) -> list[dict[str, Any]]:
        return self.db.fetchall(
            """
            SELECT platform,
                   COALESCE(SUM(CASE WHEN amount_base>0 THEN amount_base ELSE 0 END),0) AS revenue,
                   COALESCE(SUM(CASE WHEN amount_base<0 THEN amount_base ELSE 0 END),0) AS costs,
                   COALESCE(SUM(amount_base),0) AS profit
            FROM income
            WHERE platform IS NOT NULL
            GROUP BY platform
            ORDER BY profit DESC
            """
        )

    def update_platform_stats(self, platform: str, **deltas: float | int) -> None:
        row = self.db.fetchone("SELECT * FROM platform_stats WHERE platform=?", (platform,))
        if not row:
            self.db.execute(
                "INSERT INTO platform_stats(platform, updated_at) VALUES(?,?)",
                (platform, utcnow()),
            )
            row = {"accepted": 0, "completed": 0, "rejected": 0, "paid": 0, "revenue_base": 0, "cost_base": 0, "losses_streak": 0, "enabled": 1}
        fields = []
        values: list[Any] = []
        for key, delta in deltas.items():
            fields.append(f"{key}=?")
            values.append((row.get(key) or 0) + delta)
        fields.append("updated_at=?")
        values.append(utcnow())
        values.append(platform)
        self.db.execute(f"UPDATE platform_stats SET {', '.join(fields)} WHERE platform=?", tuple(values))
