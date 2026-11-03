"""SMART WORK DISTRIBUTOR — PC + 4 Android worker lanes."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import psutil

from centbot.core.logger import get_logger

log = get_logger("centbot.distributor")

WORKER_ROLES = {
    "pc": "Python/Web/API/data",
    "android_1": "mobile_discovery",
    "android_2": "mobile_execution",
    "android_3": "parallel_execution_qa",
    "android_4": "priority_and_reserve",
}


@dataclass
class WorkerSlot:
    worker_id: str
    role: str
    kind: str  # pc | android
    capacity: int = 1
    active: int = 0
    serial: str | None = None
    load: float = 0.0


@dataclass
class SmartWorkDistributor:
    """Assign tasks to PC vs Android workers without duplicate execution."""

    max_pc: int = 4
    android_slots: int = 4
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _claimed: set[str] = field(default_factory=set)
    _assignments: dict[str, str] = field(default_factory=dict)
    workers: dict[str, WorkerSlot] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workers:
            self.workers = {
                "pc": WorkerSlot("pc", WORKER_ROLES["pc"], "pc", capacity=self.max_pc),
                "android_1": WorkerSlot("android_1", WORKER_ROLES["android_1"], "android"),
                "android_2": WorkerSlot("android_2", WORKER_ROLES["android_2"], "android"),
                "android_3": WorkerSlot("android_3", WORKER_ROLES["android_3"], "android"),
                "android_4": WorkerSlot("android_4", WORKER_ROLES["android_4"], "android"),
            }
            # Disable unused android slots when fewer AVDs available
            for i in range(self.android_slots + 1, 5):
                wid = f"android_{i}"
                if wid in self.workers:
                    self.workers[wid].capacity = 0

    def bind_android_serials(self, serials: list[str]) -> None:
        with self._lock:
            for i, serial in enumerate(serials[:4], start=1):
                wid = f"android_{i}"
                if wid in self.workers:
                    self.workers[wid].serial = serial
                    self.workers[wid].capacity = max(1, self.workers[wid].capacity)

    def rebalance_roles(self) -> None:
        """Shift android roles under load: overloaded execution pulls from reserve."""
        with self._lock:
            loads = {wid: w.active / max(1, w.capacity) for wid, w in self.workers.items() if w.kind == "android"}
            if not loads:
                return
            busy = max(loads, key=loads.get)  # type: ignore[arg-type]
            idle = min(loads, key=loads.get)  # type: ignore[arg-type]
            if loads[busy] >= 1.0 and loads[idle] == 0 and idle != busy:
                # Temporarily share execution role
                self.workers[idle].role = self.workers[busy].role
                log.info("Rebalanced %s role -> %s", idle, self.workers[busy].role)

    def _category_lane(self, category: str) -> str:
        cat = (category or "other").lower()
        if cat in {"android"}:
            return "android"
        if cat in {"browser", "csv", "excel", "json_xml", "pdf", "image", "text", "programming", "other"}:
            return "pc"
        return "pc"

    def system_load(self) -> dict[str, float]:
        vm = psutil.virtual_memory()
        return {
            "cpu_percent": float(psutil.cpu_percent(interval=0.0)),
            "ram_percent": float(vm.percent),
        }

    def can_accept(self, task_id: str) -> bool:
        with self._lock:
            return task_id not in self._claimed

    def assign(self, task_row: dict[str, Any]) -> dict[str, Any]:
        """Pick a worker for a task; refuse duplicates."""
        task_id = str(task_row.get("id") or "")
        if not task_id:
            return {"ok": False, "error": "missing_task_id"}
        load = self.system_load()
        with self._lock:
            if task_id in self._claimed:
                return {"ok": False, "error": "duplicate_task", "worker": self._assignments.get(task_id)}
            lane = self._category_lane(str(task_row.get("category") or ""))
            priority = int(task_row.get("priority") or 50)
            candidates: list[str]
            if lane == "android":
                if priority >= 80:
                    candidates = ["android_4", "android_2", "android_3", "android_1"]
                else:
                    candidates = ["android_2", "android_3", "android_4", "android_1"]
            else:
                candidates = ["pc"]
                # If PC saturated and android has browser-capable reserve — keep on PC only for non-android
            chosen = None
            for wid in candidates:
                w = self.workers.get(wid)
                if not w or w.capacity <= 0:
                    continue
                if w.active >= w.capacity:
                    continue
                if load["ram_percent"] > 92 and w.kind == "android":
                    continue
                chosen = wid
                break
            if not chosen:
                return {"ok": False, "error": "no_capacity", "load": load}
            self._claimed.add(task_id)
            self._assignments[task_id] = chosen
            self.workers[chosen].active += 1
            return {
                "ok": True,
                "worker": chosen,
                "role": self.workers[chosen].role,
                "serial": self.workers[chosen].serial,
                "load": load,
            }

    def release(self, task_id: str) -> None:
        with self._lock:
            wid = self._assignments.pop(task_id, None)
            self._claimed.discard(task_id)
            if wid and wid in self.workers:
                self.workers[wid].active = max(0, self.workers[wid].active - 1)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "workers": {
                    wid: {
                        "role": w.role,
                        "kind": w.kind,
                        "active": w.active,
                        "capacity": w.capacity,
                        "serial": w.serial,
                    }
                    for wid, w in self.workers.items()
                },
                "claimed": len(self._claimed),
                "assignments": dict(self._assignments),
                "load": self.system_load(),
            }
