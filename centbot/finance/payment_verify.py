"""Confirm payouts only after real transaction evidence."""

from __future__ import annotations

import re
from typing import Any

TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
SETTLED = {"settled", "released", "paid", "verified", "received", "confirmed"}


def extract_payment_fields(pay: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pay, dict):
        return {"status": None, "tx_hash": None, "amount": None, "currency": None}
    payment = pay.get("payment") if isinstance(pay.get("payment"), dict) else pay
    status = payment.get("payment_status") or payment.get("status")
    nested = payment.get("payment")
    if not status and isinstance(nested, dict):
        status = nested.get("status") or nested.get("payment_status")
    tx_hash = payment.get("payment_tx_hash") or payment.get("tx_hash") or payment.get("txid") or payment.get("transaction_hash")
    task_obj = payment.get("task") if isinstance(payment.get("task"), dict) else None
    if task_obj:
        status = status or task_obj.get("payment_status") or task_obj.get("status")
        tx_hash = tx_hash or task_obj.get("payment_tx_hash")
    amount = payment.get("amount") or payment.get("amount_display")
    currency = payment.get("currency") or payment.get("token") or "USDC"
    return {"status": status, "tx_hash": tx_hash, "amount": amount, "currency": currency, "raw": payment}


def is_real_tx_ref(tx_ref: str | None) -> bool:
    if not tx_ref:
        return False
    if tx_ref.startswith(("sim-", "dryrun-", "local-")):
        return False
    if TX_HASH_RE.match(tx_ref):
        return True
    # Platform composite refs allowed only if they don't look synthetic
    if "-payout" in tx_ref and not tx_ref.startswith(("sim", "dry")):
        return False  # synthetic fallback without chain proof
    return len(tx_ref) >= 12


def confirm_payment(pay_response: dict[str, Any] | None, *, require_tx: bool = True) -> dict[str, Any]:
    """Return ok only when platform status is settled and (for crypto) a real tx exists."""
    fields = extract_payment_fields(pay_response)
    status = str(fields.get("status") or "").lower()
    tx_hash = fields.get("tx_hash")
    settled = status in SETTLED or status.endswith("settled")
    tx_ok = is_real_tx_ref(str(tx_hash) if tx_hash else None)
    if not settled:
        return {"ok": False, "reason": "not_settled", **fields}
    if require_tx and not tx_ok:
        return {"ok": False, "reason": "missing_or_invalid_tx", **fields}
    return {"ok": True, "reason": "confirmed", **fields}
