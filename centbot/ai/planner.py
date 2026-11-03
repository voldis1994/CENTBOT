"""AI work planner."""

from __future__ import annotations

from typing import Any

from centbot.ai.analyzer import AITaskAnalyzer


class AIWorkPlanner:
    def __init__(self, analyzer: AITaskAnalyzer):
        self.analyzer = analyzer

    def plan(self, task: dict[str, Any]) -> dict[str, Any]:
        analysis = self.analyzer.analyze(task)
        steps = analysis.get("steps") or ["execute"]
        return {
            "task_id": task.get("id"),
            "category": task.get("category"),
            "steps": [{"name": s, "status": "pending"} for s in steps],
            "estimated_hours": task.get("estimated_hours"),
            "analysis": analysis,
        }
