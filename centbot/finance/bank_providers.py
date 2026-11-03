"""External bank/payment-provider evidence for fiat payouts.

Platform ``settled`` + a reference string is never enough. CENTBOT requires a
provider (Wise / PayPal / SEPA statement API) confirmation that matches amount,
currency, and destination.
"""

from __future__ import annotations

from typing import Any, Protocol

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.bank_providers")

COMPLETED = {"completed", "settled", "received", "paid", "success", "succeeded", "cleared"}


class BankProviderClient(Protocol):
    def fetch_transfer(self, reference: str) -> dict[str, Any]:
        ...


class HttpBankProvider:
    """Generic REST provider: GET {base}/transfers/{reference} with Bearer token."""

    def __init__(self, base_url: str, api_key: str = "", *, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def fetch_transfer(self, reference: str) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "error": "provider_base_url_missing"}
        headers = {"User-Agent": "CENTBOT/1.0", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/transfers/{reference}"
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 404:
                return {"ok": False, "error": "provider_transfer_not_found", "status_code": 404}
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                return {"ok": False, "error": "provider_invalid_payload"}
            return {"ok": True, "transfer": data, "source": "provider_api", "url": url}
        except Exception as exc:  # noqa: BLE001
            log.warning("Bank provider fetch failed: %s", exc)
            return {"ok": False, "error": "provider_api_error", "detail": str(exc)}


def normalize_provider_transfer(raw: dict[str, Any]) -> dict[str, Any]:
    """Map common provider fields into a canonical transfer record."""
    status = str(
        raw.get("status")
        or raw.get("state")
        or raw.get("transfer_status")
        or raw.get("payment_status")
        or ""
    ).lower()
    amount = raw.get("amount")
    if isinstance(amount, dict):
        currency = amount.get("currency") or raw.get("currency")
        amount = amount.get("value") or amount.get("amount")
    else:
        currency = raw.get("currency") or raw.get("amount_currency")
    dest = (
        raw.get("destination_iban")
        or raw.get("iban")
        or raw.get("targetAccount")
        or raw.get("recipient_iban")
    )
    if not dest and isinstance(raw.get("destination"), dict):
        dest = raw["destination"].get("iban")
    tx_id = raw.get("id") or raw.get("transfer_id") or raw.get("transaction_id") or raw.get("provider_tx_id")
    reference = raw.get("reference") or raw.get("customer_reference") or raw.get("bank_reference")
    return {
        "status": status,
        "amount": amount,
        "currency": str(currency or "").upper(),
        "destination_iban": dest,
        "provider_tx_id": tx_id,
        "reference": reference,
        "raw": raw,
    }


def evidence_from_payment_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Accept only explicit provider evidence blobs — never platform status alone."""
    raw = fields.get("raw") if isinstance(fields.get("raw"), dict) else {}
    evidence = (
        fields.get("provider_evidence")
        or raw.get("provider_evidence")
        or raw.get("provider_transfer")
        or raw.get("bank_transfer")
    )
    if isinstance(evidence, dict) and evidence:
        return evidence
    return None


def verify_provider_evidence(
    *,
    fields: dict[str, Any],
    expected_amount: float | None,
    expected_currency: str | None,
    expected_iban: str | None,
    provider_client: BankProviderClient | None = None,
    amount_tolerance: float = 0.01,
    allow_embedded_evidence: bool = True,
) -> dict[str, Any]:
    """Confirm fiat funds via provider API and/or embedded provider ledger evidence."""
    ref = str(fields.get("bank_reference") or fields.get("tx_hash") or "")
    provider_name = str(fields.get("provider") or "bank").lower()

    evidence = evidence_from_payment_fields(fields) if allow_embedded_evidence else None
    source = "embedded_provider_evidence"
    if evidence is None and provider_client is not None and ref:
        fetched = provider_client.fetch_transfer(ref)
        if not fetched.get("ok"):
            return {
                "ok": False,
                "reason": fetched.get("error") or "provider_fetch_failed",
                "method": "bank",
                "provider": provider_name,
            }
        evidence = fetched.get("transfer")
        source = "provider_api"
    if not isinstance(evidence, dict) or not evidence:
        return {
            "ok": False,
            "reason": "provider_evidence_required",
            "method": "bank",
            "provider": provider_name,
            "hint": "Platform settled+reference is insufficient; attach provider_evidence or configure bank provider API.",
        }

    transfer = normalize_provider_transfer(evidence)
    status = str(transfer.get("status") or "").lower()
    if status not in COMPLETED and not status.endswith("settled"):
        return {
            "ok": False,
            "reason": "provider_not_completed",
            "method": "bank",
            "provider": provider_name,
            "provider_status": status,
            "source": source,
        }

    try:
        amount = float(transfer["amount"]) if transfer.get("amount") is not None else None
    except (TypeError, ValueError):
        amount = None
    if amount is None:
        return {"ok": False, "reason": "provider_amount_missing", "method": "bank", "source": source}

    currency = str(transfer.get("currency") or expected_currency or "").upper()
    if expected_currency and currency and currency != str(expected_currency).upper():
        return {
            "ok": False,
            "reason": "provider_currency_mismatch",
            "method": "bank",
            "expected": expected_currency,
            "observed": currency,
            "source": source,
        }
    if expected_amount is not None and abs(amount - float(expected_amount)) > amount_tolerance:
        return {
            "ok": False,
            "reason": "provider_amount_mismatch",
            "method": "bank",
            "expected": expected_amount,
            "observed": amount,
            "source": source,
        }

    dest = transfer.get("destination_iban")
    if expected_iban:
        left = "".join(ch for ch in str(expected_iban).upper() if not ch.isspace())
        right = "".join(ch for ch in str(dest or "").upper() if not ch.isspace())
        if not right or left != right:
            return {
                "ok": False,
                "reason": "provider_iban_mismatch",
                "method": "bank",
                "expected_iban": expected_iban,
                "observed_iban": dest,
                "source": source,
            }

    provider_tx = transfer.get("provider_tx_id")
    if not provider_tx:
        return {"ok": False, "reason": "provider_tx_id_required", "method": "bank", "source": source}

    return {
        "ok": True,
        "reason": "bank_provider_confirmed",
        "method": "bank",
        "provider": provider_name,
        "provider_tx_id": provider_tx,
        "bank_reference": ref,
        "amount": amount,
        "currency": currency,
        "iban": dest or expected_iban,
        "source": source,
        "provider_status": status,
    }
