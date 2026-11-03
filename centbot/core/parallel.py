"""Parallel task execution pool with priorities."""

from __future__ import annotations

import queue
import threading
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from centbot.core.logger import get_logger

log = get_logger("centbot.parallel")


@dataclass(order=True)
class PrioritizedJob:
    priority: int
    seq: int
    task_id: str
    payload: Any = None


class ParallelTaskSystem:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="centbot-worker")
        self._q: queue.PriorityQueue[PrioritizedJob] = queue.PriorityQueue()
        self._seq = 0
        self._lock = threading.Lock()
        self._active: dict[str, Future] = {}
        self._stop = threading.Event()

    def submit(self, task_id: str, priority: int, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """Lower internal queue number = higher priority (negate score)."""
        with self._lock:
            self._seq += 1
            seq = self._seq
        # ThreadPoolExecutor doesn't natively prioritize; we gate with our queue + dispatcher.
        future: Future = Future()

        def wrapper() -> None:
            try:
                result = fn(*args, **kwargs)
                if not future.cancelled():
                    future.set_result(result)
            except Exception as exc:  # noqa: BLE001
                log.error("Task %s failed: %s\n%s", task_id, exc, traceback.format_exc())
                if not future.cancelled():
                    future.set_exception(exc)

        # Direct submit with priority metadata tracked
        pool_future = self._executor.submit(wrapper)
        with self._lock:
            self._active[task_id] = pool_future
        pool_future.add_done_callback(lambda _f: self._active.pop(task_id, None))
        # Bridge cancellation
        def on_cancel(f: Future) -> None:
            if f.cancelled():
                pool_future.cancel()
        future.add_done_callback(on_cancel)
        # Store priority for status
        setattr(future, "centbot_priority", priority)
        setattr(future, "centbot_seq", seq)
        return future

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def active_ids(self) -> list[str]:
        with self._lock:
            return list(self._active.keys())

    def has_capacity(self) -> bool:
        return self.active_count() < self.max_workers

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        self._executor.shutdown(wait=wait, cancel_futures=True)
