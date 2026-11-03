"""Confirm crypto payouts with on-chain evidence (Base), not opaque reference strings."""

from __future__ import annotations

import re
from typing import Any

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.payment_verify")

TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
SETTLED = {"settled", "released", "paid", "verified", "received", "confirmed"}

# Base mainnet
DEFAULT_RPC = "https://mainnet.base.org"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Native ETH/token decimals
TOKEN_META = {
    "USDC": {"address": USDC_BASE.lower(), "decimals": 6},
    "USDT": {"address": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2".lower(), "decimals": 6},
}


def extract_payment_fields(pay: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pay, dict):
        return {"status": None, "tx_hash": None, "amount": None, "currency": None, "to_address": None}
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
    to_address = (
        payment.get("to")
        or payment.get("to_address")
        or payment.get("recipient")
        or payment.get("wallet_address")
        or payment.get("payTo")
    )
    return {
        "status": status,
        "tx_hash": tx_hash,
        "amount": amount,
        "currency": currency,
        "to_address": to_address,
        "network": payment.get("network") or payment.get("chain") or "eip155:8453",
        "raw": payment,
    }


def is_real_tx_ref(tx_ref: str | None) -> bool:
    """Accept only canonical 32-byte hex transaction hashes."""
    if not tx_ref:
        return False
    if tx_ref.startswith(("sim-", "dryrun-", "local-")):
        return False
    return bool(TX_HASH_RE.match(tx_ref))


def _rpc(method: str, params: list[Any], rpc_url: str) -> Any:
    resp = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=20,
        headers={"User-Agent": "CENTBOT/1.0", "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("result")


def _topic_address(topic: str) -> str:
    # 32-byte topic -> last 20 bytes as address
    h = topic.lower().replace("0x", "")
    return "0x" + h[-40:]


def verify_on_chain(
    tx_hash: str,
    *,
    expected_to: str | None,
    expected_amount: float | None,
    currency: str = "USDC",
    rpc_url: str = DEFAULT_RPC,
    min_confirmations: int = 1,
    amount_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Verify tx exists, is mined, and matches recipient/amount/token when provided."""
    if not is_real_tx_ref(tx_hash):
        return {"ok": False, "reason": "invalid_tx_hash"}

    try:
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash], rpc_url)
        head_hex = _rpc("eth_blockNumber", [], rpc_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("RPC verify failed: %s", exc)
        return {"ok": False, "reason": "rpc_error", "error": str(exc)}

    if not receipt:
        return {"ok": False, "reason": "tx_not_found_or_pending"}
    if str(receipt.get("status", "0x0")).lower() not in {"0x1", "1"}:
        return {"ok": False, "reason": "tx_reverted", "receipt_status": receipt.get("status")}

    block_hex = receipt.get("blockNumber")
    if not block_hex:
        return {"ok": False, "reason": "unmined"}
    block_no = int(block_hex, 16)
    head = int(head_hex, 16)
    confirmations = max(0, head - block_no + 1)
    if confirmations < min_confirmations:
        return {
            "ok": False,
            "reason": "insufficient_confirmations",
            "confirmations": confirmations,
            "required": min_confirmations,
        }

    currency_u = (currency or "USDC").upper()
    meta = TOKEN_META.get(currency_u)
    matched_transfer = None
    issues: list[str] = []

    if meta:
        token = meta["address"]
        decimals = meta["decimals"]
        for log_item in receipt.get("logs") or []:
            if str(log_item.get("address", "")).lower() != token:
                continue
            topics = log_item.get("topics") or []
            if not topics or str(topics[0]).lower() != TRANSFER_TOPIC:
                continue
            if len(topics) < 3:
                continue
            to_addr = _topic_address(topics[2])
            raw_amount = int(log_item.get("data") or "0x0", 16)
            amount = raw_amount / (10 ** decimals)
            entry = {"to": to_addr, "amount": amount, "token": currency_u}
            if expected_to and to_addr.lower() != expected_to.lower():
                continue
            if expected_amount is not None and abs(amount - float(expected_amount)) > amount_tolerance:
                continue
            matched_transfer = entry
            break
        if matched_transfer is None:
            # Collect any USDC transfers for diagnostics
            transfers = []
            for log_item in receipt.get("logs") or []:
                if str(log_item.get("address", "")).lower() != token:
                    continue
                topics = log_item.get("topics") or []
                if len(topics) >= 3 and str(topics[0]).lower() == TRANSFER_TOPIC:
                    transfers.append(
                        {
                            "to": _topic_address(topics[2]),
                            "amount": int(log_item.get("data") or "0x0", 16) / (10 ** decimals),
                        }
                    )
            return {
                "ok": False,
                "reason": "transfer_mismatch",
                "confirmations": confirmations,
                "expected_to": expected_to,
                "expected_amount": expected_amount,
                "observed_transfers": transfers[:5],
            }
    else:
        # Native transfer fallback
        try:
            tx = _rpc("eth_getTransactionByHash", [tx_hash], rpc_url) or {}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "rpc_error", "error": str(exc)}
        to_addr = (tx.get("to") or "").lower()
        value = int(tx.get("value") or "0x0", 16) / 1e18
        if expected_to and to_addr != expected_to.lower():
            issues.append("recipient_mismatch")
        if expected_amount is not None and abs(value - float(expected_amount)) > amount_tolerance:
            issues.append("amount_mismatch")
        if issues:
            return {
                "ok": False,
                "reason": "native_transfer_mismatch",
                "issues": issues,
                "to": to_addr,
                "amount": value,
                "confirmations": confirmations,
            }
        matched_transfer = {"to": to_addr, "amount": value, "token": currency_u}

    return {
        "ok": True,
        "reason": "on_chain_confirmed",
        "tx_hash": tx_hash,
        "confirmations": confirmations,
        "transfer": matched_transfer,
        "block_number": block_no,
    }


def confirm_payment(
    pay_response: dict[str, Any] | None,
    *,
    require_tx: bool = True,
    expected_wallet: str | None = None,
    expected_amount: float | None = None,
    rpc_url: str = DEFAULT_RPC,
    min_confirmations: int = 1,
    verify_chain: bool = True,
) -> dict[str, Any]:
    """Settled platform status + canonical tx hash + optional on-chain match."""
    fields = extract_payment_fields(pay_response)
    status = str(fields.get("status") or "").lower()
    tx_hash = fields.get("tx_hash")
    settled = status in SETTLED or status.endswith("settled")
    if not settled:
        return {"ok": False, "reason": "not_settled", **fields}
    if require_tx and not is_real_tx_ref(str(tx_hash) if tx_hash else None):
        return {"ok": False, "reason": "missing_or_invalid_tx", **fields}

    wallet = expected_wallet or fields.get("to_address")
    amount = expected_amount if expected_amount is not None else fields.get("amount")
    try:
        amount_f = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_f = None

    if verify_chain and require_tx:
        chain = verify_on_chain(
            str(tx_hash),
            expected_to=wallet,
            expected_amount=amount_f,
            currency=str(fields.get("currency") or "USDC"),
            rpc_url=rpc_url,
            min_confirmations=min_confirmations,
        )
        if not chain.get("ok"):
            return {**fields, **chain, "ok": False}
        return {**fields, **chain, "ok": True, "reason": "confirmed"}

    return {"ok": True, "reason": "confirmed_platform_only", **fields}
