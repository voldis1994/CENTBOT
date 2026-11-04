"""Cross-config consistency audit — catch false/true mismatches before run."""

from __future__ import annotations

from typing import Any

from centbot.core.config import Config


def audit_config(config: Config) -> dict[str, Any]:
    """Return blockers/warnings. Live start is never hard-blocked by this report."""
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    mode = str(config.get("system.mode", "live")).lower()
    live = mode == "live"
    auto_accept = bool(config.get("analysis.auto_accept", True))
    android_on = bool(config.get("android.enabled", True))
    max_emu = int(config.get("android.max_emulators", 0) or 0)
    max_parallel = int(config.get("system.max_parallel_tasks", 0) or 0)
    wallet = str(config.get("finance.crypto_wallet_public") or "").strip()
    iban = str(config.get("finance.bank_iban") or "").strip()
    simulate = bool(config.get("finance.simulate_rewards_in_dry_run", False))
    reconcile = bool(config.get("finance.reconcile_payments", True))
    verify_chain = bool(config.get("finance.verify_on_chain", True))
    browser_on = bool(config.get("browser.enabled", True))
    dashboard_on = bool(config.get("dashboard.enabled", True))
    auto_register = bool(config.get("discovery.auto_register_allowed", True))

    if simulate:
        blockers.append("finance.simulate_rewards_in_dry_run_must_be_false")

    if live and not auto_accept:
        warnings.append("analysis.auto_accept_false_claims_disabled")
    if live and not wallet:
        warnings.append("finance.crypto_wallet_public_missing_crypto_booking_will_fail")
    if live and not reconcile:
        warnings.append("finance.reconcile_payments_is_false_live_will_not_book_income")
    if live and not verify_chain:
        warnings.append("finance.verify_on_chain_is_false_crypto_booking_weakened")

    if not live:
        notes.append("system.mode_is_dry_run_claims_disabled")

    if android_on and max_emu < 1:
        warnings.append("android.enabled_true_but_max_emulators_lt_1")
    if not android_on and max_emu >= 4:
        warnings.append("android.max_emulators_is_4_but_android.enabled_is_false")
    if android_on and max_parallel < max_emu:
        warnings.append(
            f"system.max_parallel_tasks({max_parallel})_lt_android.max_emulators({max_emu})_pool_will_starve_android_workers"
        )

    if not browser_on:
        notes.append("browser.enabled_false_web_tasks_unavailable")
    if not dashboard_on:
        warnings.append("dashboard.enabled_false_control_panel_off")

    if iban and not str(config.get("finance.bank_provider_base_url") or "").strip():
        warnings.append("bank_iban_set_without_bank_provider_base_url_fiat_booking_blocked")

    if wallet.upper().startswith("0XYOUR") or "PLACEHOLDER" in wallet.upper():
        warnings.append("finance.crypto_wallet_public_looks_like_placeholder")
    if "XXXX" in iban.upper():
        warnings.append("finance.bank_iban_looks_like_placeholder")

    ready_for_live = (
        live
        and not simulate
        and bool(wallet)
        and not wallet.upper().startswith("0XYOUR")
        and "PLACEHOLDER" not in wallet.upper()
    )

    return {
        "ok": not simulate,
        "ready_for_live": ready_for_live,
        "mode": mode,
        "flags": {
            "live": live,
            "auto_accept": auto_accept,
            "android.enabled": android_on,
            "android.max_emulators": max_emu,
            "system.max_parallel_tasks": max_parallel,
            "browser.enabled": browser_on,
            "dashboard.enabled": dashboard_on,
            "reconcile_payments": reconcile,
            "verify_on_chain": verify_chain,
            "simulate_rewards_in_dry_run": simulate,
            "auto_register_allowed": auto_register,
            "wallet_set": bool(wallet),
            "iban_set": bool(iban),
        },
        "blockers": blockers,
        "warnings": warnings,
        "notes": notes,
    }
