"""Secure credential storage (Fernet encryption at rest)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


class CredentialStore:
    def __init__(self, path: Path, key_env: str = "CENTBOT_SECRET_KEY"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key_env = key_env
        self._fernet = Fernet(self._load_or_create_key())

    def _key_file(self) -> Path:
        return self.path.parent / ".centbot_key"

    def _load_or_create_key(self) -> bytes:
        env = os.environ.get(self.key_env)
        if env:
            return env.encode() if not env.startswith("gAAAA") else env.encode()
        # Prefer dedicated key file (Fernet key)
        key_path = self._key_file()
        if key_path.exists():
            return key_path.read_bytes().strip()
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def save(self, data: dict[str, Any]) -> None:
        token = self._fernet.encrypt(json.dumps(data).encode("utf-8"))
        self.path.write_bytes(token)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        raw = self._fernet.decrypt(self.path.read_bytes())
        return json.loads(raw.decode("utf-8"))

    def set(self, key: str, value: Any) -> None:
        data = self.load()
        data[key] = value
        self.save(data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get(key, default)
