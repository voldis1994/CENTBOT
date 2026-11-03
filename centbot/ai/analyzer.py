"""AI task analyzer."""

from __future__ import annotations

from typing import Any

from centbot.ai.ollama_client import OllamaClient


class AITaskAnalyzer:
    def __init__(self, client: OllamaClient, enabled: bool = False):
        self.client = client
        self.enabled = enabled

    def analyze(self, task: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return self._heuristic(task)
        prompt = (
            "Analyze this paid task. Reply with short JSON keys: risks, steps, skills.\n"
            f"Title: {task.get('title')}\nDescription: {task.get('description')}\n"
        )
        result = self.client.generate(prompt)
        if not result.get("ok"):
            return {**self._heuristic(task), "ai_error": result.get("error")}
        return {"ok": True, "mode": "ollama", "response": result.get("response"), **self._heuristic(task)}

    def _heuristic(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "heuristic",
            "risks": [] if task.get("funded") else ["unfunded"],
            "steps": ["analyze", "execute", "verify", "submit"],
            "skills": [task.get("category") or "general"],
        }
