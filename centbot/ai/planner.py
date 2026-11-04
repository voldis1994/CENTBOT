"""AI work planner — structured steps executors actually consume."""

from __future__ import annotations

from typing import Any

from centbot.ai.analyzer import AITaskAnalyzer


class AIWorkPlanner:
    def __init__(self, analyzer: AITaskAnalyzer):
        self.analyzer = analyzer

    def plan(self, task: dict[str, Any]) -> dict[str, Any]:
        analysis = self.analyzer.analyze(task)
        raw_steps = analysis.get("steps") or ["execute"]
        category = task.get("category") or analysis.get("skills", ["other"])[0]
        structured: list[dict[str, Any]] = []
        for i, step in enumerate(raw_steps):
            if isinstance(step, dict):
                name = str(step.get("name") or step.get("id") or f"step_{i}")
                structured.append(
                    {
                        "id": f"s{i+1}",
                        "name": name,
                        "status": step.get("status") or "pending",
                        "action": step.get("action") or _action_for(name, category),
                        "inputs": step.get("inputs") or analysis.get("required_files") or [],
                        "outputs": step.get("outputs") or [],
                    }
                )
            else:
                name = str(step)
                structured.append(
                    {
                        "id": f"s{i+1}",
                        "name": name,
                        "status": "pending",
                        "action": _action_for(name, str(category)),
                        "inputs": list(analysis.get("required_files") or []),
                        "outputs": [],
                    }
                )
        # Ensure a verify + submit tail for live workflow
        names = {s["name"] for s in structured}
        if "verify_acceptance" not in names and "verify" not in names:
            structured.append(
                {
                    "id": f"s{len(structured)+1}",
                    "name": "verify_acceptance",
                    "status": "pending",
                    "action": "verify",
                    "inputs": [],
                    "outputs": list(analysis.get("acceptance_criteria") or []),
                }
            )
        if "submit" not in names:
            structured.append(
                {
                    "id": f"s{len(structured)+1}",
                    "name": "submit",
                    "status": "pending",
                    "action": "submit",
                    "inputs": [],
                    "outputs": ["submission"],
                }
            )
        return {
            "task_id": task.get("id"),
            "category": category,
            "goal": analysis.get("goal"),
            "conditions": analysis.get("conditions") or [],
            "required_files": analysis.get("required_files") or [],
            "acceptance_criteria": analysis.get("acceptance_criteria") or [],
            "create_vs_transform": analysis.get("create_vs_transform") or "transform",
            "steps": structured,
            "estimated_hours": task.get("estimated_hours"),
            "analysis": analysis,
            "executor_hint": str(category),
        }


def _action_for(name: str, category: str) -> str:
    n = name.lower()
    if "gather" in n or "input" in n:
        return "fetch_inputs"
    if "create" in n or "generat" in n:
        return f"create_{category}"
    if "verify" in n or "accept" in n:
        return "verify"
    if "submit" in n:
        return "submit"
    if "understand" in n or "analy" in n:
        return "analyze"
    return f"execute_{category}"
