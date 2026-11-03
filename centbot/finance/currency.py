"""Multi-currency support with simple FX table."""

from __future__ import annotations

# Approximate static rates to USD for offline/demo operation.
RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "USDT": 1.0,
    "USDC": 1.0,
    "BTC": 65000.0,
    "ETH": 3500.0,
}


def to_base(amount: float, currency: str, base: str = "USD") -> float:
    c = currency.upper()
    b = base.upper()
    if c not in RATES_TO_USD or b not in RATES_TO_USD:
        return amount
    usd = amount * RATES_TO_USD[c]
    return usd / RATES_TO_USD[b]


def convert(amount: float, src: str, dst: str) -> float:
    return to_base(amount, src, dst)
