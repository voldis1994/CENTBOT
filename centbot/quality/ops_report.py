"""Operations evidence report — only facts from journal/DB/ledger (no simulated success)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from centbot.core.database import Database
from centbot.finance.ledger import FinanceLedger


def _parse_journal_line(line: str) -> dict[str, Any] | None:
    # Format from ActionJournal: timestamp | LEVEL | ... or JSON lines — support both
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    return None


def build_operations_report(
    *,
    db: Database,
    ledger: FinanceLedger,
    journal_dir: Path,
    mode: str,
    live: bool,
) -> dict[str, Any]:
    """Assemble a verifiable ops report from durable storage."""
    discovered = db.fetchall("SELECT id, platform, external_id, title, status, reward_amount, reward_currency, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 200")
    accepted_live = db.fetchall(
        "SELECT id, platform, external_id, title, status, reward_amount, reward_currency, updated_at FROM tasks "
        "WHERE status IN ('accepted','submitted','verified','paid','completed','failed') "
        "AND status NOT LIKE 'dry_run%' ORDER BY updated_at DESC LIMIT 100"
    )
    submissions = db.fetchall(
        "SELECT * FROM submissions WHERE status NOT IN ('dry_run_submitted') ORDER BY id DESC LIMIT 100"
    )
    income = ledger.income_history(100)
    bank_income = [r for r in income if r.get("kind") == "bank"]
    crypto_income = [r for r in income if r.get("kind") == "crypto"]
    balances = ledger.balances()

    # Journal actions (best-effort)
    journal_actions: list[dict[str, Any]] = []
    journal_path = Path(journal_dir) / "actions.jsonl"
    if journal_path.exists():
        try:
            lines = journal_path.read_text(encoding="utf-8").splitlines()[-500:]
            for line in lines:
                try:
                    journal_actions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    real_accepts = [a for a in journal_actions if a.get("action") == "accept" and a.get("status") == "ok"]
    dry_accepts = [a for a in journal_actions if a.get("action") == "accept" and a.get("status") == "dry_run"]
    real_submits = [a for a in journal_actions if a.get("action") == "submit" and a.get("status") in {"submitted", "ok"}]
    payments = [a for a in journal_actions if a.get("action") == "payment_received" and a.get("status") == "ok"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "live": live,
        "disclaimer": "Only ledger-backed income and non-dry_run submissions count as real success.",
        "discovery": {
            "tasks_seen": len(discovered),
            "samples": [
                {
                    "id": t.get("id"),
                    "platform": t.get("platform"),
                    "title": (t.get("title") or "")[:80],
                    "status": t.get("status"),
                    "reward": t.get("reward_amount"),
                    "currency": t.get("reward_currency"),
                }
                for t in discovered[:30]
            ],
        },
        "accepted": {
            "live_rows": len(accepted_live),
            "journal_real_accepts": len(real_accepts),
            "journal_dry_run_accepts": len(dry_accepts),
            "samples": accepted_live[:20],
        },
        "submissions": {
            "platform_submissions": len(submissions),
            "journal_real_submits": len(real_submits),
            "samples": submissions[:20],
        },
        "payments": {
            "bank_count": len(bank_income),
            "crypto_count": len(crypto_income),
            "journal_payment_received": len(payments),
            "bank_samples": bank_income[:20],
            "crypto_samples": crypto_income[:20],
        },
        "finances": {
            "bank_balance": balances.get("bank"),
            "crypto_balance": balances.get("crypto"),
            "total_profit": balances.get("profit"),
            "cash_after_withdrawals": balances.get("cash"),
        },
        "verified_success": {
            "has_real_submission": len(submissions) > 0,
            "has_verified_income": len(bank_income) + len(crypto_income) > 0,
            "profit_positive": float(balances.get("profit") or 0) > 0,
        },
    }
    return report


def write_operations_report(path: Path, report: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
