"""Ollama client for local small models."""

from __future__ import annotations

from typing import Any

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.ai.ollama")


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "tinyllama", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception as exc:  # noqa: BLE001
            log.debug("list_models failed: %s", exc)
            return []

    def generate(self, prompt: str) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "ollama_unavailable", "hint": "Install Ollama and pull a small model, e.g. `ollama pull tinyllama`."}
        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            return {"ok": True, "response": data.get("response", ""), "raw": data}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
