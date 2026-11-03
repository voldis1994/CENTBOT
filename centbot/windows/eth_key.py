"""Store / clear the Ethereum signing key used for TaskMarket / BountyBook claims.

Public payout address (finance.crypto_wallet_public) is NOT enough to claim —
platforms require EIP-191 signatures from a private key.

Usage (Windows):
  SET_ETH_KEY.bat
  or: python -m centbot.windows.eth_key set
  or: set CENTBOT_ETH_PRIVATE_KEY=0x... then START.bat

Never ask for / store seed phrases or mnemonics — only a single signing private key.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Any

from centbot.platforms.auth_ethereum import EthWallet, wallet_from_env, wallet_from_store
from centbot.runtime_paths import install_root
from centbot.security.credentials import CredentialStore


def _store(root: Path | None = None) -> CredentialStore:
    base = Path(root) if root else install_root()
    return CredentialStore(base / "data" / "credentials.enc")


def signing_wallet_status(root: Path | None = None) -> dict[str, Any]:
    env_w = wallet_from_env("CENTBOT_ETH_PRIVATE_KEY")
    stored = wallet_from_store(_store(root).get("eth_wallet"))
    w = env_w or stored
    return {
        "loaded": bool(w),
        "source": "env" if env_w else ("credentials" if stored else None),
        "address": w.address if w else None,
        "hint_lv": (
            "Parakstīšanas maks ielādēts — TaskMarket/BountyBook claim iespējams."
            if w
            else "Trūkst ETH privātās atslēgas. Palaid SET_ETH_KEY.bat (publiskā adrese claimam nepietiek)."
        ),
    }


def set_private_key(private_key: str, *, root: Path | None = None) -> dict[str, Any]:
    key = (private_key or "").strip()
    if not key:
        return {"ok": False, "error": "empty_key"}
    # Refuse seed phrases / mnemonics (word lists)
    if " " in key.strip() and len(key.split()) >= 12:
        return {"ok": False, "error": "seed_phrase_forbidden", "hint": "Use a single hex private key, never a mnemonic."}
    if not key.startswith("0x"):
        key = "0x" + key
    if len(key) != 66:
        return {"ok": False, "error": "invalid_key_length", "hint": "Expected 0x + 64 hex chars"}
    try:
        from eth_account import Account

        account = Account.from_key(key)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid_key:{exc}"}
    wallet = EthWallet(private_key=key, address=account.address)
    store = _store(root)
    store.set("eth_wallet", {"private_key": wallet.private_key, "address": wallet.address})
    # Optional: also write env file for START.bat (gitignored)
    base = Path(root) if root else install_root()
    env_path = base / "data" / "eth.env"
    try:
        env_path.write_text(f"CENTBOT_ETH_PRIVATE_KEY={wallet.private_key}\n", encoding="utf-8")
        try:
            env_path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass
    return {
        "ok": True,
        "address": wallet.address,
        "stored": True,
        "path": str(store.path),
        "env_file": str(env_path) if env_path.exists() else None,
        "note": "Restart CENTBOT (STOP.bat then START.bat) so claim uses the new key.",
    }


def clear_private_key(*, root: Path | None = None) -> dict[str, Any]:
    store = _store(root)
    data = store.load()
    data.pop("eth_wallet", None)
    store.save(data)
    base = Path(root) if root else install_root()
    env_path = base / "data" / "eth.env"
    if env_path.exists():
        try:
            env_path.unlink()
        except OSError:
            pass
    return {"ok": True, "cleared": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CENTBOT ETH signing key helper")
    parser.add_argument("action", choices=["set", "status", "clear"], nargs="?", default="set")
    parser.add_argument("--key", default="", help="Private key hex (prefer interactive prompt)")
    args = parser.parse_args(argv)

    if args.action == "status":
        print(signing_wallet_status())
        return 0
    if args.action == "clear":
        print(clear_private_key())
        return 0

    key = args.key or os.environ.get("CENTBOT_ETH_PRIVATE_KEY", "").strip()
    if not key:
        print("Ievadi ETH privāto atslēgu claim/parakstīšanai (0x…).")
        print("NEIEVADI seed frāzi / mnemonic. Publiskā adrese claimam NEPITIEk.")
        try:
            key = getpass.getpass("Private key: ").strip()
        except EOFError:
            key = ""
    result = set_private_key(key)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
