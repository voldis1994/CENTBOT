"""Supported payment platform integrations (public receive + verification stubs)."""

from __future__ import annotations

from typing import Any

SUPPORTED = {
    "bank_transfer": {"type": "bank", "manual": True},
    "paypal": {"type": "bank", "manual": True},
    "wise": {"type": "bank", "manual": True},
    "usdt_trc20": {"type": "crypto", "manual": False},
    "btc": {"type": "crypto", "manual": False},
    "eth": {"type": "crypto", "manual": False},
}


class PaymentIntegrations:
    def __init__(self, wallet_public: str = ""):
        self.wallet_public = wallet_public

    def list_supported(self) -> dict[str, Any]:
        return dict(SUPPORTED)

    def receive_address(self, method: str) -> dict[str, Any]:
        info = SUPPORTED.get(method)
        if not info:
            return {"ok": False, "error": "unsupported_method"}
        if info["type"] == "crypto":
            if not self.wallet_public:
                return {"ok": False, "error": "wallet_not_configured"}
            return {"ok": True, "method": method, "address": self.wallet_public}
        return {"ok": True, "method": method, "manual": True, "notes": "Configure bank details offline; never commit secrets."}
