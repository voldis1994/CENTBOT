"""First-run configuration wizard — writes config/local.yaml + SecretStore.

Never asks for bank password, card CVV, or crypto seed phrases.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from centbot.core.config import ROOT
from centbot.windows.install_state import SetupProgress
from centbot.windows.secrets import ForbiddenSecretError, SecretStore

IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,20}$")

OPTIONAL_KEYS = {"phone", "swift_bic", "bank_provider", "bank_provider_url", "task_types"}


def validate_field(name: str, value: str, *, required: bool = True) -> str | None:
    value = (value or "").strip()
    if not value:
        if not required or name in OPTIONAL_KEYS:
            return None
        return f"{name}_required"
    if name == "email" and not EMAIL_RE.match(value):
        return "invalid_email"
    if name == "phone" and not PHONE_RE.match(value):
        return "invalid_phone"
    if name == "iban":
        compact = value.replace(" ", "").upper()
        if not IBAN_RE.match(compact):
            return "invalid_iban"
    if name == "crypto_wallet" and value.startswith("0x") and not ETH_RE.match(value):
        return "invalid_eth_address"
    if name == "mode" and value.lower() not in {"dry_run", "live"}:
        return "invalid_mode"
    if name == "min_profit":
        try:
            if float(value) < 0:
                return "min_profit_negative"
        except ValueError:
            return "invalid_min_profit"
    return None


def build_local_yaml(answers: dict[str, Any]) -> dict[str, Any]:
    mode = str(answers.get("mode") or "dry_run").lower()
    task_types = answers.get("task_types") or []
    if isinstance(task_types, str):
        task_types = [t.strip() for t in task_types.split(",") if t.strip()]
    preferred_crypto = answers.get("preferred_crypto") or ["USDC"]
    if isinstance(preferred_crypto, str):
        preferred_crypto = [c.strip() for c in preferred_crypto.split(",") if c.strip()]
    return {
        "system": {"mode": mode},
        "operator": {
            "full_name": answers.get("full_name") or "",
            "country": answers.get("country") or "",
            "email": answers.get("email") or "",
            "phone": answers.get("phone") or "",
        },
        "analysis": {
            "auto_accept": mode == "live" and bool(answers.get("auto_accept", False)),
            "min_expected_profit": float(answers.get("min_profit") or 0.25),
            "preferred_categories": task_types,
        },
        "finance": {
            "bank_account_holder": answers.get("bank_holder") or "",
            "bank_iban": (answers.get("iban") or "").replace(" ", "").upper(),
            "bank_swift_bic": answers.get("swift_bic") or "",
            "bank_currency": (answers.get("bank_currency") or "EUR").upper(),
            "bank_provider_base_url": answers.get("bank_provider_url") or "",
            "crypto_wallet_public": answers.get("crypto_wallet") or "",
            "crypto_network": answers.get("crypto_network") or "base",
            "preferred_crypto": preferred_crypto,
            "reconcile_payments": True,
            "verify_on_chain": True,
            "simulate_rewards_in_dry_run": False,
        },
        "android": {
            "enabled": True,
            "max_emulators": 4,
            "default_avd": "CENTBOT_ANDROID_01",
            "avds": [
                "CENTBOT_ANDROID_01",
                "CENTBOT_ANDROID_02",
                "CENTBOT_ANDROID_03",
                "CENTBOT_ANDROID_04",
            ],
        },
        "notifications": {
            "email": bool(answers.get("notify_email", True)),
            "desktop": bool(answers.get("notify_desktop", True)),
        },
        "platforms": {
            "auto_register": bool(answers.get("auto_register", False)),
        },
        "discovery": {
            "auto_register_allowed": bool(answers.get("auto_register", False)),
        },
    }


def write_local_yaml(data: dict[str, Any], path: Path | None = None) -> Path:
    path = Path(path) if path else ROOT / "config" / "local.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def apply_answers(
    answers: dict[str, Any],
    *,
    root: Path | None = None,
    store_secrets: bool = True,
    allow_partial: bool = True,
) -> dict[str, Any]:
    root = Path(root) if root else ROOT
    errors: dict[str, str] = {}

    required_text = ["full_name", "country", "email", "bank_holder", "iban", "crypto_wallet", "mode"]
    for key in required_text:
        raw = str(answers.get(key) or "").strip()
        if not raw and not allow_partial:
            errors[key] = f"{key}_required"
    for key in ("email", "phone", "iban", "crypto_wallet", "mode", "min_profit"):
        raw = str(answers.get(key) or "")
        if not raw.strip() and key in OPTIONAL_KEYS:
            continue
        if not raw.strip() and key == "min_profit":
            continue
        if not raw.strip() and allow_partial and key in required_text:
            continue
        err = validate_field(key, raw, required=False)
        if err:
            errors[key] = err

    for bad in ("bank_password", "card_cvv", "seed_phrase", "mnemonic"):
        if answers.get(bad):
            errors[bad] = "forbidden_secret"

    if errors and not allow_partial:
        return {"ok": False, "errors": errors}
    if any(v == "forbidden_secret" for v in errors.values()):
        return {"ok": False, "errors": errors}

    local = build_local_yaml(answers)
    path = write_local_yaml(local, root / "config" / "local.yaml")

    secret_keys_written: list[str] = []
    if store_secrets:
        store = SecretStore(root / "data")
        for sk in ("bank_provider_api_key", "bountybook_api_key", "platform_api_token"):
            if answers.get(sk):
                try:
                    store.set(sk, str(answers[sk]))
                    secret_keys_written.append(sk)
                except ForbiddenSecretError as exc:
                    errors[sk] = str(exc)

    progress = SetupProgress(root / "data" / "setup" / "progress.json")
    progress.mark("wizard", ok=True, detail=f"local={path}")

    return {
        "ok": True,
        "path": str(path),
        "errors": {k: v for k, v in errors.items() if v != "forbidden_secret"},
        "local": local,
        "secrets_stored": secret_keys_written,
        "refused_secrets": ["bank_password", "card_cvv", "seed_phrase", "mnemonic"],
    }


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{suffix}: ")
    except EOFError:
        return default
    return val.strip() or default


def run_interactive_wizard(*, root: Path | None = None) -> dict[str, Any]:
    print("=== CENTBOT pirmreizējās konfigurācijas vednis ===")
    print("Nekad neievadiet bankas paroli, kartes CVV vai kripto seed frāzi.\n")
    answers: dict[str, Any] = {
        "full_name": _prompt("Vārds un uzvārds"),
        "country": _prompt("Valsts", "Latvia"),
        "email": _prompt("E-pasta adrese"),
        "phone": _prompt("Telefona numurs (neobligāti)"),
        "bank_holder": _prompt("Bankas konta īpašnieks"),
        "iban": _prompt("Bankas IBAN"),
        "swift_bic": _prompt("SWIFT/BIC (neobligāti)"),
        "bank_currency": _prompt("Bankas valūta", "EUR"),
        "bank_provider": _prompt("Bankas/maksājumu pakalpojums (piem. Wise)", "Wise"),
        "bank_provider_url": _prompt("Bankas API base URL (neobligāti)"),
        "crypto_wallet": _prompt("Publiskā kriptomaka saņemšanas adrese"),
        "crypto_network": _prompt("Kriptovalūtas tīkls", "base"),
        "preferred_crypto": [x.strip() for x in _prompt("Vēlamās kriptovalūtas", "USDC").split(",") if x.strip()],
        "min_profit": _prompt("Minimālā pieņemamā peļņa", "0.25"),
        "task_types": _prompt("Vēlamie uzdevumu veidi (komatā)", "csv,text,programming,browser"),
        "notify_email": _prompt("E-pasta paziņojumi (y/n)", "y").lower().startswith("y"),
        "notify_desktop": _prompt("Darbvirsmas paziņojumi (y/n)", "y").lower().startswith("y"),
        "auto_register": _prompt("Atļaut automātisku platformu reģistrāciju (y/n)", "n").lower().startswith("y"),
        "auto_accept": _prompt("Live auto-accept uzdevumus (y/n)", "n").lower().startswith("y"),
        "mode": _prompt("Darbības režīms (dry_run/live)", "dry_run"),
    }
    return apply_answers(answers, root=root, allow_partial=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--json-file" in argv:
        idx = argv.index("--json-file")
        path = Path(argv[idx + 1])
        import json

        answers = json.loads(path.read_text(encoding="utf-8"))
        result = apply_answers(answers, allow_partial="--partial" in argv)
        print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))
        return 0 if result.get("ok") else 1
    result = run_interactive_wizard()
    print(yaml.safe_dump({"ok": result.get("ok"), "path": result.get("path"), "errors": result.get("errors")}, allow_unicode=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
