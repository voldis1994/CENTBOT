"""Confirm payouts with chain-specific on-chain evidence or bank transfer proofs."""

from __future__ import annotations

import re
from typing import Any

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.payment_verify")

TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
SETTLED = {"settled", "released", "paid", "verified", "received", "confirmed"}
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}$")
BANK_REF_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-_/]{5,64}$", re.I)

# Multi-chain registry (EVM). Token addresses are per-chain USDC/USDT where known.
CHAINS: dict[str, dict[str, Any]] = {
    "base": {
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "aliases": {"base", "base-mainnet", "eip155:8453", "8453"},
        "tokens": {
            "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "decimals": 6},
            "USDT": {"address": "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2", "decimals": 6},
        },
    },
    "ethereum": {
        "chain_id": 1,
        "rpc": "https://ethereum.publicnode.com",
        "aliases": {"ethereum", "eth", "mainnet", "eip155:1", "1"},
        "tokens": {
            "USDC": {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6},
            "USDT": {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
        },
    },
    "optimism": {
        "chain_id": 10,
        "rpc": "https://mainnet.optimism.io",
        "aliases": {"optimism", "op", "eip155:10", "10"},
        "tokens": {
            "USDC": {"address": "0x0b2c639c533813f4aa9d7837caf62653d097ff85", "decimals": 6},
            "USDT": {"address": "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58", "decimals": 6},
        },
    },
    "arbitrum": {
        "chain_id": 42161,
        "rpc": "https://arb1.arbitrum.io/rpc",
        "aliases": {"arbitrum", "arb", "eip155:42161", "42161"},
        "tokens": {
            "USDC": {"address": "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "decimals": 6},
            "USDT": {"address": "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9", "decimals": 6},
        },
    },
    "polygon": {
        "chain_id": 137,
        "rpc": "https://polygon-rpc.com",
        "aliases": {"polygon", "matic", "eip155:137", "137"},
        "tokens": {
            "USDC": {"address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "decimals": 6},
            "USDT": {"address": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f", "decimals": 6},
        },
    },
}

DEFAULT_RPC = CHAINS["base"]["rpc"]
# Back-compat aliases used by older tests
USDC_BASE = CHAINS["base"]["tokens"]["USDC"]["address"]
TOKEN_META = {k: dict(v) for k, v in CHAINS["base"]["tokens"].items()}


def resolve_chain(network: str | None) -> dict[str, Any]:
    raw = str(network or "base").strip().lower()
    for name, meta in CHAINS.items():
        if raw == name or raw in meta["aliases"]:
            return {"name": name, **meta}
    # Unknown EVM chain id form eip155:N — require explicit rpc via caller
    m = re.match(r"eip155:(\d+)$", raw)
    if m:
        return {
            "name": f"eip155:{m.group(1)}",
            "chain_id": int(m.group(1)),
            "rpc": None,
            "aliases": {raw},
            "tokens": {},
            "unknown": True,
        }
    return {"name": "base", **CHAINS["base"], "fallback": True}


def extract_payment_fields(pay: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pay, dict):
        return {
            "status": None,
            "tx_hash": None,
            "amount": None,
            "currency": None,
            "to_address": None,
            "method": None,
            "iban": None,
            "bank_reference": None,
        }
    payment = pay.get("payment") if isinstance(pay.get("payment"), dict) else pay
    status = payment.get("payment_status") or payment.get("status")
    nested = payment.get("payment")
    if not status and isinstance(nested, dict):
        status = nested.get("status") or nested.get("payment_status")
    tx_hash = (
        payment.get("payment_tx_hash")
        or payment.get("tx_hash")
        or payment.get("txid")
        or payment.get("transaction_hash")
    )
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
    method = str(payment.get("method") or payment.get("payment_method") or payment.get("rail") or "").lower()
    if not method:
        if payment.get("iban") or payment.get("bank_reference") or currency.upper() in {"EUR", "USD", "GBP"}:
            if not tx_hash:
                method = "bank"
        if not method:
            method = "crypto"
    return {
        "status": status,
        "tx_hash": tx_hash,
        "amount": amount,
        "currency": currency,
        "to_address": to_address,
        "network": payment.get("network") or payment.get("chain") or "eip155:8453",
        "method": method,
        "iban": payment.get("iban") or payment.get("account_iban"),
        "bank_reference": payment.get("bank_reference") or payment.get("reference") or payment.get("payment_reference"),
        "provider": payment.get("provider") or payment.get("bank") or payment.get("rail_provider"),
        "raw": payment,
    }


def is_real_tx_ref(tx_ref: str | None) -> bool:
    """Accept only canonical 32-byte hex transaction hashes."""
    if not tx_ref:
        return False
    if tx_ref.startswith(("sim-", "dryrun-", "local-")):
        return False
    return bool(TX_HASH_RE.match(tx_ref))


def is_bank_reference(ref: str | None) -> bool:
    if not ref:
        return False
    if ref.startswith(("sim-", "dryrun-", "local-")):
        return False
    return bool(BANK_REF_RE.match(ref)) and not TX_HASH_RE.match(ref)


def is_iban(value: str | None) -> bool:
    if not value:
        return False
    compact = re.sub(r"\s+", "", value).upper()
    return bool(IBAN_RE.match(compact))


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
    h = topic.lower().replace("0x", "")
    return "0x" + h[-40:]


def verify_on_chain(
    tx_hash: str,
    *,
    expected_to: str | None,
    expected_amount: float | None,
    currency: str = "USDC",
    rpc_url: str | None = None,
    network: str | None = None,
    min_confirmations: int = 1,
    amount_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Verify tx on the resolved chain (Base/Ethereum/OP/Arb/Polygon, …)."""
    if not is_real_tx_ref(tx_hash):
        return {"ok": False, "reason": "invalid_tx_hash"}

    chain = resolve_chain(network)
    rpc = rpc_url or chain.get("rpc") or DEFAULT_RPC
    if not rpc:
        return {"ok": False, "reason": "unsupported_chain", "network": chain.get("name")}

    try:
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash], rpc)
        head_hex = _rpc("eth_blockNumber", [], rpc)
    except Exception as exc:  # noqa: BLE001
        log.warning("RPC verify failed (%s): %s", chain.get("name"), exc)
        return {"ok": False, "reason": "rpc_error", "error": str(exc), "network": chain.get("name")}

    if not receipt:
        return {"ok": False, "reason": "tx_not_found_or_pending", "network": chain.get("name")}
    if str(receipt.get("status", "0x0")).lower() not in {"0x1", "1"}:
        return {
            "ok": False,
            "reason": "tx_reverted",
            "receipt_status": receipt.get("status"),
            "network": chain.get("name"),
        }

    block_hex = receipt.get("blockNumber")
    if not block_hex:
        return {"ok": False, "reason": "unmined", "network": chain.get("name")}
    block_no = int(block_hex, 16)
    head = int(head_hex, 16)
    confirmations = max(0, head - block_no + 1)
    if confirmations < min_confirmations:
        return {
            "ok": False,
            "reason": "insufficient_confirmations",
            "confirmations": confirmations,
            "required": min_confirmations,
            "network": chain.get("name"),
        }

    currency_u = (currency or "USDC").upper()
    tokens = chain.get("tokens") or {}
    meta = tokens.get(currency_u)
    matched_transfer = None
    issues: list[str] = []

    if meta:
        token = str(meta["address"]).lower()
        decimals = int(meta["decimals"])
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
            entry = {"to": to_addr, "amount": amount, "token": currency_u, "chain": chain.get("name")}
            if expected_to and to_addr.lower() != expected_to.lower():
                continue
            if expected_amount is not None and abs(amount - float(expected_amount)) > amount_tolerance:
                continue
            matched_transfer = entry
            break
        if matched_transfer is None:
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
                "network": chain.get("name"),
            }
    else:
        try:
            tx = _rpc("eth_getTransactionByHash", [tx_hash], rpc) or {}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "rpc_error", "error": str(exc), "network": chain.get("name")}
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
                "network": chain.get("name"),
            }
        matched_transfer = {"to": to_addr, "amount": value, "token": currency_u, "chain": chain.get("name")}

    return {
        "ok": True,
        "reason": "on_chain_confirmed",
        "tx_hash": tx_hash,
        "confirmations": confirmations,
        "transfer": matched_transfer,
        "block_number": block_no,
        "network": chain.get("name"),
        "chain_id": chain.get("chain_id"),
    }


def verify_bank_payment(
    pay_response: dict[str, Any] | None,
    *,
    expected_amount: float | None = None,
    expected_currency: str | None = None,
    expected_iban: str | None = None,
    amount_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Verify a bank/SEPA/Wise/PayPal-style payout separately from crypto rails."""
    fields = extract_payment_fields(pay_response)
    status = str(fields.get("status") or "").lower()
    settled = status in SETTLED or status.endswith("settled")
    if not settled:
        return {"ok": False, "reason": "not_settled", "method": "bank", **fields}

    iban = expected_iban or fields.get("iban")
    if iban and not is_iban(str(iban)):
        return {"ok": False, "reason": "invalid_iban", "method": "bank", **fields}
    if expected_iban and iban and re.sub(r"\s+", "", str(iban)).upper() != re.sub(r"\s+", "", expected_iban).upper():
        return {"ok": False, "reason": "iban_mismatch", "method": "bank", **fields}

    ref = fields.get("bank_reference") or fields.get("tx_hash")
    if not is_bank_reference(str(ref) if ref else None):
        return {"ok": False, "reason": "missing_or_invalid_bank_reference", "method": "bank", **fields}

    amount = expected_amount if expected_amount is not None else fields.get("amount")
    try:
        amount_f = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_amount", "method": "bank", **fields}
    if amount_f is None:
        return {"ok": False, "reason": "amount_required", "method": "bank", **fields}

    currency = str(expected_currency or fields.get("currency") or "").upper()
    if currency in {"USDC", "USDT", "ETH", "BTC"}:
        return {"ok": False, "reason": "crypto_currency_on_bank_rail", "method": "bank", **fields}
    if not currency:
        return {"ok": False, "reason": "currency_required", "method": "bank", **fields}

    if expected_amount is not None and abs(amount_f - float(expected_amount)) > amount_tolerance:
        return {"ok": False, "reason": "amount_mismatch", "method": "bank", **fields}

    return {
        "ok": True,
        "reason": "bank_confirmed",
        "method": "bank",
        "bank_reference": ref,
        "iban": iban,
        "amount": amount_f,
        "currency": currency,
        "provider": fields.get("provider"),
        "status": status,
    }


_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_eth_address(value: str | None) -> bool:
    return bool(value and _ADDR_RE.match(value))


def confirm_payment(
    pay_response: dict[str, Any] | None,
    *,
    require_tx: bool = True,
    expected_wallet: str | None = None,
    expected_amount: float | None = None,
    rpc_url: str | None = None,
    min_confirmations: int = 1,
    verify_chain: bool = True,
    expected_iban: str | None = None,
) -> dict[str, Any]:
    """Dispatch to bank or multi-chain crypto verification."""
    fields = extract_payment_fields(pay_response)
    method = str(fields.get("method") or "crypto").lower()
    if method in {"bank", "bank_transfer", "sepa", "wise", "paypal", "fiat"}:
        return verify_bank_payment(
            pay_response,
            expected_amount=expected_amount,
            expected_currency=str(fields.get("currency") or "") or None,
            expected_iban=expected_iban,
        )

    status = str(fields.get("status") or "").lower()
    tx_hash = fields.get("tx_hash")
    settled = status in SETTLED or status.endswith("settled")
    if not settled:
        return {"ok": False, "reason": "not_settled", **fields}
    if require_tx and not is_real_tx_ref(str(tx_hash) if tx_hash else None):
        return {"ok": False, "reason": "missing_or_invalid_tx", **fields}

    wallet = expected_wallet or fields.get("to_address")
    if not is_eth_address(str(wallet) if wallet else None):
        return {"ok": False, "reason": "recipient_required", **fields, "to_address": wallet}

    amount = expected_amount if expected_amount is not None else fields.get("amount")
    try:
        amount_f = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_f = None

    chain = resolve_chain(fields.get("network"))
    if verify_chain and require_tx:
        on_chain = verify_on_chain(
            str(tx_hash),
            expected_to=str(wallet),
            expected_amount=amount_f,
            currency=str(fields.get("currency") or "USDC"),
            rpc_url=rpc_url or chain.get("rpc"),
            network=chain.get("name"),
            min_confirmations=min_confirmations,
        )
        if not on_chain.get("ok"):
            return {**fields, **on_chain, "ok": False, "to_address": wallet, "method": "crypto"}
        return {
            **fields,
            **on_chain,
            "ok": True,
            "reason": "confirmed",
            "to_address": wallet,
            "method": "crypto",
        }

    return {
        "ok": True,
        "reason": "confirmed_platform_only",
        **fields,
        "to_address": wallet,
        "method": "crypto",
        "network": chain.get("name"),
    }
