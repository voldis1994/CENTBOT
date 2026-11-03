"""Configuration system for CENTBOT."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from centbot.runtime_paths import bundle_root, ensure_install_layout, install_root

# Durable install root (next to CENTBOT.exe). Never use _MEIPASS for writes.
ROOT = install_root()
_BUNDLE = bundle_root()
_DEFAULT_CANDIDATES = (
    _BUNDLE / "config" / "default.yaml",
    ROOT / "config" / "default.yaml",
)
DEFAULT_CONFIG_PATH = next((p for p in _DEFAULT_CANDIDATES if p.exists()), ROOT / "config" / "default.yaml")
LOCAL_CONFIG_PATH = ROOT / "config" / "local.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    """Loads YAML config with optional local overrides and env expansion."""

    def __init__(self, path: str | Path | None = None, overrides: dict[str, Any] | None = None):
        ensure_install_layout()
        # Refresh roots in case CENTBOT_ROOT was set after module import
        global ROOT, LOCAL_CONFIG_PATH, DEFAULT_CONFIG_PATH
        ROOT = install_root()
        LOCAL_CONFIG_PATH = ROOT / "config" / "local.yaml"
        bundled = bundle_root() / "config" / "default.yaml"
        DEFAULT_CONFIG_PATH = bundled if bundled.exists() else ROOT / "config" / "default.yaml"
        if path is None:
            self.path = DEFAULT_CONFIG_PATH
        else:
            p = Path(path)
            self.path = p if p.is_absolute() else ROOT / p
        if not self.path.exists():
            ensure_install_layout()
            alt = ROOT / "config" / "default.yaml"
            if alt.exists():
                self.path = alt
        self._data = self._load()
        if overrides:
            self._data = _deep_merge(self._data, overrides)

    def _load(self) -> dict[str, Any]:
        with open(self.path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        # Always merge durable local.yaml next to the exe — never from _MEIPASS
        local = install_root() / "config" / "local.yaml"
        if local.exists():
            with open(local, encoding="utf-8") as fh:
                data = _deep_merge(data, yaml.safe_load(fh) or {})
        return data

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        return value if isinstance(value, dict) else {}

    def path_from(self, dotted: str, default: str | None = None) -> Path:
        raw = self.get(dotted, default)
        if not raw:
            raise KeyError(dotted)
        p = Path(str(raw))
        root = install_root()
        return p if p.is_absolute() else root / p

    def env(self, name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def platform_api_key(self, platform: str) -> str:
        env_name = self.get(f"platforms.{platform}.api_key_env", "")
        return self.env(env_name) if env_name else ""

    def is_dry_run(self) -> bool:
        return str(self.get("system.mode", "dry_run")).lower() == "dry_run"

    def is_live(self) -> bool:
        return str(self.get("system.mode", "dry_run")).lower() == "live"

    def force_dry_run(self) -> None:
        """Hard-lock system.mode to dry_run (used by --controlled-live)."""
        system = self._data.setdefault("system", {})
        if not isinstance(system, dict):
            self._data["system"] = {"mode": "dry_run"}
            return
        system["mode"] = "dry_run"

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value

    def save_local(self, patch: dict[str, Any], path: Path | None = None) -> Path:
        """Merge ``patch`` into durable config/local.yaml next to the exe (never secrets)."""
        root = install_root()
        local_path = Path(path) if path else root / "config" / "local.yaml"
        # Guard: never write into PyInstaller extract dir (vanishes on exit)
        mei = getattr(__import__("sys"), "_MEIPASS", None)
        if mei and str(local_path).startswith(str(mei)):
            local_path = root / "config" / "local.yaml"
        existing: dict[str, Any] = {}
        if local_path.exists():
            with open(local_path, encoding="utf-8") as fh:
                existing = yaml.safe_load(fh) or {}
        merged = _deep_merge(existing, patch)
        finance = merged.get("finance")
        if isinstance(finance, dict):
            for bad in ("bank_password", "seed_phrase", "mnemonic", "private_key", "card_cvv"):
                finance.pop(bad, None)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self._data = _deep_merge(self._data, patch)
        return local_path

    @property
    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def reload(self) -> None:
        self._data = self._load()
