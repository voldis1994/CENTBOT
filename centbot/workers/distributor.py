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

# Strict fixed mapping — never remap by "first available serial"
AVD_TO_WORKER = {
    "CENTBOT_ANDROID_01": "android_1",
    "CENTBOT_ANDROID_02": "android_2",
    "CENTBOT_ANDROID_03": "android_3",
    "CENTBOT_ANDROID_04": "android_4",
}
WORKER_TO_AVD = {v: k for k, v in AVD_TO_WORKER.items()}


@dataclass
class WorkerSlot:
    worker_id: str
    role: str
    kind: str  # pc | android
    capacity: int = 1
    active: int = 0
    serial: str | None = None
    avd: str | None = None
    boot_completed: bool = False
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
                "android_1": WorkerSlot("android_1", WORKER_ROLES["android_1"], "android", avd=WORKER_TO_AVD["android_1"]),
                "android_2": WorkerSlot("android_2", WORKER_ROLES["android_2"], "android", avd=WORKER_TO_AVD["android_2"]),
                "android_3": WorkerSlot("android_3", WORKER_ROLES["android_3"], "android", avd=WORKER_TO_AVD["android_3"]),
                "android_4": WorkerSlot("android_4", WORKER_ROLES["android_4"], "android", avd=WORKER_TO_AVD["android_4"]),
            }
            for i in range(self.android_slots + 1, 5):
                wid = f"android_{i}"
                if wid in self.workers:
                    self.workers[wid].capacity = 0

    def bind_android_serials(self, serials: list[str]) -> None:
        """Deprecated positional bind — MUST NOT be used for live mapping.

        Kept for back-compat tests; clears nothing and does not remapa by order.
        Prefer ``bind_android_slots`` with explicit AVD names.
        """
        log.warning("bind_android_serials ignored — use bind_android_slots(AVD→worker) for strict mapping")

    def bind_android_slots(self, slots: list[dict[str, Any]]) -> None:
        """Strict AVD→worker bind. Capacity only when serial + boot_completed."""
        with self._lock:
            # Reset android slots first so stale serials cannot linger on wrong workers
            for wid, w in self.workers.items():
                if w.kind != "android":
                    continue
                expected_avd = WORKER_TO_AVD.get(wid)
                w.avd = expected_avd
                w.serial = None
                w.boot_completed = False
                w.capacity = 0

            for slot in slots:
                avd = str(slot.get("avd") or "")
                wid = AVD_TO_WORKER.get(avd) or str(slot.get("worker") or "")
                # Enforce AVD name wins over any caller-supplied worker id
                if avd in AVD_TO_WORKER:
                    wid = AVD_TO_WORKER[avd]
                if wid not in self.workers or self.workers[wid].kind != "android":
                    continue
                # Reject mismatched worker/avd pairs
                if avd and WORKER_TO_AVD.get(wid) and avd != WORKER_TO_AVD[wid]:
                    log.error("Rejected AVD/worker mismatch: avd=%s worker=%s", avd, wid)
                    continue
                serial = slot.get("serial")
                boot_ok = bool(slot.get("boot_completed") or slot.get("boot_ok"))
                connected = bool(serial) and boot_ok
                self.workers[wid].avd = avd or WORKER_TO_AVD.get(wid)
                self.workers[wid].serial = str(serial) if serial else None
                self.workers[wid].boot_completed = boot_ok
                # Only assign work after ADB + sys.boot_completed=1
                self.workers[wid].capacity = 1 if connected else 0

    def rebalance_roles(self) -> None:
        """Shift android roles under load: overloaded execution pulls from reserve."""
        with self._lock:
            loads = {
                wid: w.active / max(1, w.capacity)
                for wid, w in self.workers.items()
                if w.kind == "android" and w.capacity > 0
            }
            if not loads:
                return
            busy = max(loads, key=loads.get)  # type: ignore[arg-type]
            idle = min(loads, key=loads.get)  # type: ignore[arg-type]
            if loads[busy] >= 1.0 and loads[idle] == 0 and idle != busy:
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
            chosen = None
            for wid in candidates:
                w = self.workers.get(wid)
                if not w or w.capacity <= 0:
                    continue
                if w.active >= w.capacity:
                    continue
                # Android: require live serial + boot_completed (capacity already gates, double-check)
                if w.kind == "android":
                    if not w.serial or not w.boot_completed:
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
                "avd": self.workers[chosen].avd,
                "boot_completed": self.workers[chosen].boot_completed,
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
                        "avd": w.avd,
                        "boot_completed": w.boot_completed,
                    }
                    for wid, w in self.workers.items()
                },
                "claimed": len(self._claimed),
                "assignments": dict(self._assignments),
                "load": self.system_load(),
            }
