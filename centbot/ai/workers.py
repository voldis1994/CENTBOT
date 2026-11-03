"""Specialized worker coordination."""

from __future__ import annotations

from typing import Any, Callable

from centbot.core.logger import get_logger

log = get_logger("centbot.workers")


class WorkerCoordinator:
    def __init__(self) -> None:
        self._workers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(self, name: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._workers[name] = fn

    def available(self) -> list[str]:
        return sorted(self._workers)

    def run_subtasks(self, subtasks: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
        results = []
        for sub in subtasks:
            worker = sub.get("worker", "system")
            fn = self._workers.get(worker) or self._workers.get("system")
            if not fn:
                results.append({**sub, "status": "skipped", "error": "no_worker"})
                continue
            try:
                out = fn({**context, "subtask": sub})
                results.append({**sub, "status": "done", "result": out})
            except Exception as exc:  # noqa: BLE001
                log.exception("Worker %s failed", worker)
                results.append({**sub, "status": "error", "error": str(exc)})
        return results
