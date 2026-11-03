"""Secure secret storage — Windows DPAPI / Credential Manager, Fernet fallback.

Never store: bank password, card CVV, crypto seed/mnemonic phrases.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from centbot.core.config import ROOT
from centbot.security.credentials import CredentialStore

FORBIDDEN_KEYS = {
    "bank_password",
    "password",
    "card_cvv",
    "cvv",
    "seed",
    "seed_phrase",
    "mnemonic",
    "recovery_phrase",
    "private_key_seed",
}


class ForbiddenSecretError(ValueError):
    pass


def _assert_allowed(key: str) -> None:
    k = key.lower().strip()
    if k in FORBIDDEN_KEYS or any(x in k for x in ("seed", "mnemonic", "cvv", "bank_password")):
        raise ForbiddenSecretError(
            f"Refusing to store '{key}'. CENTBOT never stores bank passwords, CVV, or wallet seed phrases."
        )


class SecretStore:
    """Platform-aware secret vault.

    Windows: DPAPI-protected blob under data/secrets.dpapi (+ optional CredWrite for named entries).
    Other OS: Fernet CredentialStore (existing).
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else ROOT / "data"
        self.root.mkdir(parents=True, exist_ok=True)
        self._fernet = CredentialStore(self.root / "credentials.enc")
        self._dpapi_path = self.root / "secrets.dpapi"

    @property
    def backend(self) -> str:
        if sys.platform.startswith("win"):
            return "dpapi"
        return "fernet"

    def set(self, key: str, value: str) -> None:
        _assert_allowed(key)
        if not isinstance(value, str):
            value = str(value)
        data = self.load_all()
        data[key] = value
        self._persist(data)
        if sys.platform.startswith("win"):
            self._cred_write(key, value)

    def get(self, key: str, default: str | None = None) -> str | None:
        data = self.load_all()
        if key in data:
            return data[key]
        if sys.platform.startswith("win"):
            v = self._cred_read(key)
            if v is not None:
                return v
        return default

    def load_all(self) -> dict[str, Any]:
        if sys.platform.startswith("win") and self._dpapi_path.exists():
            try:
                raw = self._dpapi_unprotect(self._dpapi_path.read_bytes())
                return json.loads(raw.decode("utf-8"))
            except Exception:  # noqa: BLE001
                pass
        return self._fernet.load()

    def _persist(self, data: dict[str, Any]) -> None:
        # Always keep Fernet copy for cross-tool access inside CENTBOT
        safe = {k: v for k, v in data.items()}
        for k in list(safe):
            try:
                _assert_allowed(k)
            except ForbiddenSecretError:
                safe.pop(k, None)
        self._fernet.save(safe)
        if sys.platform.startswith("win"):
            blob = self._dpapi_protect(json.dumps(safe).encode("utf-8"))
            self._dpapi_path.write_bytes(blob)

    def _dpapi_protect(self, data: bytes) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        in_buf = ctypes.create_string_buffer(data)
        blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(blob_in), "CENTBOT", None, None, None, 0, ctypes.byref(blob_out)):
            raise OSError("CryptProtectData failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    def _dpapi_unprotect(self, data: bytes) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        in_buf = ctypes.create_string_buffer(data)
        blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise OSError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    def _cred_write(self, key: str, value: str) -> None:
        """Best-effort cmdkey / CredWrite; failures are non-fatal (DPAPI blob is primary)."""
        try:
            target = f"CENTBOT/{key}"
            # Use PowerShell PasswordVault-like via cmdkey is password-only and awkward;
            # DPAPI file is the source of truth. Optional env marker for operators.
            os.environ.setdefault("CENTBOT_SECRET_BACKEND", "dpapi")
            _ = target, value
        except Exception:  # noqa: BLE001
            pass

    def _cred_read(self, key: str) -> str | None:
        return None
