"""Configuration system for CENTBOT."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "default.yaml"


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
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self._data = self._load()
        if overrides:
            self._data = _deep_merge(self._data, overrides)

    def _load(self) -> dict[str, Any]:
        with open(self.path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        local = self.path.parent / "local.yaml"
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
        return p if p.is_absolute() else ROOT / p

    def env(self, name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def platform_api_key(self, platform: str) -> str:
        env_name = self.get(f"platforms.{platform}.api_key_env", "")
        return self.env(env_name) if env_name else ""

    def is_dry_run(self) -> bool:
        return str(self.get("system.mode", "dry_run")).lower() == "dry_run"

    def is_live(self) -> bool:
        return str(self.get("system.mode", "dry_run")).lower() == "live"

    @property
    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def reload(self) -> None:
        self._data = self._load()
