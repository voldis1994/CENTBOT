"""Store / clear the Ethereum signing key used for TaskMarket / BountyBook claims.

Public payout address (finance.crypto_wallet_public) is NOT enough to claim —
platforms require EIP-191 signatures from a private key.

Windows: prefer SET_ETH_KEY.bat (visible paste) — getpass often fails in CMD.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from centbot.platforms.auth_ethereum import EthWallet, wallet_from_env, wallet_from_store
from centbot.runtime_paths import install_root
from centbot.security.credentials import CredentialStore


def _root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    env = (os.environ.get("CENTBOT_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # Prefer cwd when it looks like a CENTBOT install (bat always cd's here)
    cwd = Path.cwd().resolve()
    if (cwd / "centbot").is_dir() and (cwd / "START.bat").exists():
        return cwd
    return install_root()


def _store(root: Path | None = None) -> CredentialStore:
    base = _root(root)
    (base / "data").mkdir(parents=True, exist_ok=True)
    return CredentialStore(base / "data" / "credentials.enc")


def normalize_private_key(raw: str) -> str:
    key = (raw or "").strip().strip('"').strip("'").replace("\r", "").replace("\n", "").replace(" ", "")
    if key.lower().startswith("0x"):
        key = "0x" + key[2:]
    elif key:
        key = "0x" + key
    return key


def signing_wallet_status(root: Path | None = None) -> dict[str, Any]:
    base = _root(root)
    env_w = wallet_from_env("CENTBOT_ETH_PRIVATE_KEY")
    # Also load eth.env into process if present (bat may not have exported yet)
    eth_env = base / "data" / "eth.env"
    if not env_w and eth_env.exists():
        try:
            for line in eth_env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("CENTBOT_ETH_PRIVATE_KEY="):
                    os.environ["CENTBOT_ETH_PRIVATE_KEY"] = line.split("=", 1)[1].strip()
                    env_w = wallet_from_env("CENTBOT_ETH_PRIVATE_KEY")
                    break
        except OSError:
            pass
    stored = None
    try:
        stored = wallet_from_store(_store(base).get("eth_wallet"))
    except Exception as exc:  # noqa: BLE001
        return {
            "loaded": bool(env_w),
            "source": "env" if env_w else None,
            "address": env_w.address if env_w else None,
            "credentials_error": str(exc),
            "root": str(base),
            "hint_lv": "eth.env vai credentials kļūda — palaid SET_ETH_KEY.bat vēlreiz.",
        }
    w = env_w or stored
    return {
        "loaded": bool(w),
        "source": "env" if env_w else ("credentials" if stored else None),
        "address": w.address if w else None,
        "root": str(base),
        "eth_env": str(eth_env) if eth_env.exists() else None,
        "hint_lv": (
            f"Parakstīšanas maks OK · {(w.address if w else '')[:10]}… — TaskMarket claim iespējams."
            if w
            else "Trūkst ETH privātās atslēgas. Palaid SET_ETH_KEY.bat un IEVADI atslēgu (redzamu)."
        ),
    }


def set_private_key(private_key: str, *, root: Path | None = None) -> dict[str, Any]:
    base = _root(root)
    (base / "data").mkdir(parents=True, exist_ok=True)
    key = normalize_private_key(private_key)
    if not key or key == "0x":
        return {"ok": False, "error": "empty_key", "hint_lv": "Atslēga tukša — ielīmē 0x… hex (64 simboli)."}
    if " " in (private_key or "") and len((private_key or "").split()) >= 12:
        return {"ok": False, "error": "seed_phrase_forbidden", "hint_lv": "Nedrīkst seed frāzi — tikai private key."}
    if len(key) != 66:
        return {
            "ok": False,
            "error": "invalid_key_length",
            "got_len": len(key),
            "hint_lv": f"Gaidīju 0x+64 hex (66 simboli), sanāca {len(key)}. Nokopē no MetaMask Account details → Private key.",
        }
    try:
        from eth_account import Account

        account = Account.from_key(key)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid_key:{exc}", "hint_lv": "Atslēga nav derīga hex."}

    wallet = EthWallet(private_key=key, address=account.address)
    store = _store(base)
    try:
        store.set("eth_wallet", {"private_key": wallet.private_key, "address": wallet.address})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"credentials_write_failed:{exc}", "root": str(base)}

    env_path = base / "data" / "eth.env"
    try:
        # UTF-8 no BOM — START.bat for /f is happier
        env_path.write_text(f"CENTBOT_ETH_PRIVATE_KEY={wallet.private_key}\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        return {
            "ok": False,
            "error": f"eth_env_write_failed:{exc}",
            "path": str(env_path),
            "hint_lv": "Nevaru rakstīt data\\eth.env — aizver CENTBOT un mēģini kā Administrators.",
        }

    # Verify round-trip
    verify = signing_wallet_status(base)
    if not verify.get("loaded"):
        return {
            "ok": False,
            "error": "verify_failed_after_write",
            "verify": verify,
            "hint_lv": "Fails ierakstīts, bet nolasīt nevar — pārbaudi data\\eth.env",
        }

    return {
        "ok": True,
        "address": wallet.address,
        "stored": True,
        "root": str(base),
        "credentials": str(store.path),
        "env_file": str(env_path),
        "verify_source": verify.get("source"),
        "hint_lv": f"SAGLABĀTS · {wallet.address} — tagad STOP.bat un START.bat",
    }


def clear_private_key(*, root: Path | None = None) -> dict[str, Any]:
    base = _root(root)
    store = _store(base)
    try:
        data = store.load()
        data.pop("eth_wallet", None)
        store.save(data)
    except Exception:  # noqa: BLE001
        pass
    env_path = base / "data" / "eth.env"
    if env_path.exists():
        try:
            env_path.unlink()
        except OSError:
            pass
    os.environ.pop("CENTBOT_ETH_PRIVATE_KEY", None)
    return {"ok": True, "cleared": True, "root": str(base)}


def _prompt_key() -> str:
    # Windows CMD: getpass often yields empty — use visible input
    print("Ievadi ETH private key (0x… 64 hex). Redzams teksts — OK šajā CMD.")
    print("NEIEVADI seed/mnemonic. Publiskā adrese NEPITIEk.")
    try:
        return input("Private key> ").strip()
    except EOFError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CENTBOT ETH signing key helper")
    parser.add_argument("action", choices=["set", "status", "clear"], nargs="?", default="set")
    parser.add_argument("--key", default="", help="Private key hex")
    args = parser.parse_args(argv)

    if args.action == "status":
        print(signing_wallet_status())
        return 0
    if args.action == "clear":
        print(clear_private_key())
        return 0

    key = args.key or os.environ.get("CENTBOT_ETH_PRIVATE_KEY", "").strip()
    if not key:
        key = _prompt_key()
    result = set_private_key(key)
    print(result)
    if result.get("ok"):
        print(result.get("hint_lv") or "OK")
    else:
        print("KĻŪDA:", result.get("hint_lv") or result.get("error"))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
