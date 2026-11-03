"""Independent bank/payment-provider verification for fiat payouts.

Platform ``settled``, reference numbers, and any evidence blob attached by the
task platform are **never** accepted as proof. CENTBOT must fetch the transfer
from a configured bank/payment-provider API and match IBAN, amount, currency,
and provider transaction id.
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
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def fetch_transfer(self, reference: str) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "error": "provider_base_url_missing"}
        if not reference:
            return {"ok": False, "error": "missing_reference"}
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


class StaticBankProvider:
    """Test double that returns a canned independent provider ledger row."""

    def __init__(self, transfers: dict[str, dict[str, Any]]):
        self.transfers = {str(k): v for k, v in transfers.items()}

    def fetch_transfer(self, reference: str) -> dict[str, Any]:
        row = self.transfers.get(str(reference))
        if not row:
            return {"ok": False, "error": "provider_transfer_not_found"}
        return {"ok": True, "transfer": row, "source": "provider_api"}


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
        "provider_tx_id": str(tx_id) if tx_id is not None else None,
        "reference": reference,
        "raw": raw,
    }


def _norm_iban(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").upper() if not ch.isspace())


def verify_via_provider_api(
    *,
    reference: str,
    expected_amount: float,
    expected_currency: str,
    expected_iban: str,
    provider_client: BankProviderClient,
    provider_name: str = "bank",
    amount_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Fetch transfer from an independent provider API and match settlement fields."""
    if provider_client is None:
        return {
            "ok": False,
            "reason": "bank_provider_not_configured",
            "method": "bank",
            "hint": "Configure finance.bank_provider_base_url (independent API).",
        }

    fetched = provider_client.fetch_transfer(reference)
    if not fetched.get("ok"):
        return {
            "ok": False,
            "reason": fetched.get("error") or "provider_fetch_failed",
            "method": "bank",
            "provider": provider_name,
        }

    evidence = fetched.get("transfer")
    if not isinstance(evidence, dict) or not evidence:
        return {"ok": False, "reason": "provider_empty_transfer", "method": "bank", "provider": provider_name}

    transfer = normalize_provider_transfer(evidence)
    status = str(transfer.get("status") or "").lower()
    if status not in COMPLETED and not status.endswith("settled"):
        return {
            "ok": False,
            "reason": "provider_not_completed",
            "method": "bank",
            "provider": provider_name,
            "provider_status": status,
            "source": "provider_api",
        }

    try:
        amount = float(transfer["amount"]) if transfer.get("amount") is not None else None
    except (TypeError, ValueError):
        amount = None
    if amount is None:
        return {"ok": False, "reason": "provider_amount_missing", "method": "bank", "source": "provider_api"}

    currency = str(transfer.get("currency") or "").upper()
    if not currency:
        return {"ok": False, "reason": "provider_currency_missing", "method": "bank", "source": "provider_api"}
    if currency != str(expected_currency).upper():
        return {
            "ok": False,
            "reason": "provider_currency_mismatch",
            "method": "bank",
            "expected": expected_currency,
            "observed": currency,
            "source": "provider_api",
        }
    if abs(amount - float(expected_amount)) > amount_tolerance:
        return {
            "ok": False,
            "reason": "provider_amount_mismatch",
            "method": "bank",
            "expected": expected_amount,
            "observed": amount,
            "source": "provider_api",
        }

    dest = transfer.get("destination_iban")
    if _norm_iban(dest) != _norm_iban(expected_iban):
        return {
            "ok": False,
            "reason": "provider_iban_mismatch",
            "method": "bank",
            "expected_iban": expected_iban,
            "observed_iban": dest,
            "source": "provider_api",
        }

    provider_tx = transfer.get("provider_tx_id")
    if not provider_tx:
        return {"ok": False, "reason": "provider_tx_id_required", "method": "bank", "source": "provider_api"}

    return {
        "ok": True,
        "reason": "bank_provider_confirmed",
        "method": "bank",
        "provider": provider_name,
        "provider_tx_id": provider_tx,
        "bank_reference": reference,
        "amount": amount,
        "currency": currency,
        "iban": dest,
        "source": "provider_api",
        "provider_status": status,
    }


# Back-compat name used by older call sites — API-only, ignores platform blobs.
def verify_provider_evidence(
    *,
    fields: dict[str, Any],
    expected_amount: float | None,
    expected_currency: str | None,
    expected_iban: str | None,
    provider_client: BankProviderClient | None = None,
    amount_tolerance: float = 0.01,
    allow_embedded_evidence: bool = False,  # noqa: ARG001 — intentionally ignored / always False
) -> dict[str, Any]:
    """API-only verification. Platform-embedded evidence is deliberately ignored."""
    ref = str(fields.get("bank_reference") or fields.get("tx_hash") or "")
    provider_name = str(fields.get("provider") or "bank").lower()
    if expected_amount is None or not expected_currency or not expected_iban:
        return {
            "ok": False,
            "reason": "bank_expected_fields_required",
            "method": "bank",
            "hint": "expected amount, currency, and IBAN are required",
        }
    if provider_client is None:
        return {
            "ok": False,
            "reason": "bank_provider_not_configured",
            "method": "bank",
            "provider": provider_name,
            "hint": "Platform settled/reference/provider_evidence are insufficient; configure an independent bank API.",
        }
    return verify_via_provider_api(
        reference=ref,
        expected_amount=float(expected_amount),
        expected_currency=str(expected_currency),
        expected_iban=str(expected_iban),
        provider_client=provider_client,
        provider_name=provider_name,
        amount_tolerance=amount_tolerance,
    )
