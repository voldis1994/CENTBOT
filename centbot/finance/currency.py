"""Multi-currency support with live FX rates and safe fallbacks."""

from __future__ import annotations

import time
from typing import Any

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.fx")

# Pegged / last-resort fallbacks used only when live fetch fails.
_FALLBACK_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "USDT": 1.0,
    "USDC": 1.0,
    "BTC": 65000.0,
    "ETH": 3500.0,
}

_CACHE: dict[str, Any] = {"rates": dict(_FALLBACK_TO_USD), "fetched_at": 0.0, "source": "fallback"}
_TTL_SECONDS = 3600.0


def refresh_rates(force: bool = False) -> dict[str, float]:
    now = time.time()
    if not force and _CACHE["rates"] and now - float(_CACHE["fetched_at"]) < _TTL_SECONDS:
        return dict(_CACHE["rates"])

    rates = dict(_FALLBACK_TO_USD)
    source = "fallback"
    try:
        # Frankfurter — free ECB-derived fiat rates, no API key
        r = requests.get("https://api.frankfurter.app/latest", params={"from": "USD"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        fiat = data.get("rates") or {}
        for code, value in fiat.items():
            # API returns USD→X; we need X→USD
            if value:
                rates[str(code).upper()] = 1.0 / float(value)
        rates["USD"] = 1.0
        source = "frankfurter"
    except Exception as exc:  # noqa: BLE001
        log.warning("Fiat FX fetch failed: %s", exc)

    try:
        # Coinbase spot for BTC/ETH
        for asset in ("BTC", "ETH"):
            c = requests.get(f"https://api.coinbase.com/v2/prices/{asset}-USD/spot", timeout=10)
            c.raise_for_status()
            amount = float((c.json().get("data") or {}).get("amount") or 0)
            if amount > 0:
                rates[asset] = amount
        if source == "frankfurter":
            source = "frankfurter+coinbase"
        elif source == "fallback":
            source = "coinbase"
    except Exception as exc:  # noqa: BLE001
        log.warning("Crypto FX fetch failed: %s", exc)

    rates["USDT"] = 1.0
    rates["USDC"] = 1.0
    _CACHE["rates"] = rates
    _CACHE["fetched_at"] = now
    _CACHE["source"] = source
    return dict(rates)


def rates_to_usd() -> dict[str, float]:
    return refresh_rates()


def fx_status() -> dict[str, Any]:
    refresh_rates()
    return {
        "source": _CACHE["source"],
        "fetched_at": _CACHE["fetched_at"],
        "currencies": sorted(_CACHE["rates"].keys()),
    }


def to_base(amount: float, currency: str, base: str = "USD") -> float:
    rates = refresh_rates()
    c = currency.upper()
    b = base.upper()
    if c not in rates or b not in rates:
        return amount
    usd = amount * rates[c]
    return usd / rates[b]


def convert(amount: float, src: str, dst: str) -> float:
    return to_base(amount, src, dst)
