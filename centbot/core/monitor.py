"""CPU, RAM, GPU and internet monitoring."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Any

import psutil
import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.monitor")


@dataclass
class SystemSnapshot:
    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    disk_percent: float
    gpu_percent: float | None
    gpu_memory_percent: float | None
    internet_ok: bool
    load_avg: tuple[float, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SystemMonitor:
    def __init__(
        self,
        cpu_warn: float = 85,
        ram_warn: float = 85,
        gpu_warn: float = 90,
        internet_url: str = "https://1.1.1.1",
    ):
        self.cpu_warn = cpu_warn
        self.ram_warn = ram_warn
        self.gpu_warn = gpu_warn
        self.internet_url = internet_url

    def _gpu_stats(self) -> tuple[float | None, float | None]:
        if not shutil.which("nvidia-smi"):
            return None, None
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=5,
            ).strip()
            if not out:
                return None, None
            line = out.splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            util = float(parts[0])
            mem_used = float(parts[1])
            mem_total = float(parts[2]) or 1.0
            return util, (mem_used / mem_total) * 100.0
        except Exception as exc:  # noqa: BLE001
            log.debug("GPU probe failed: %s", exc)
            return None, None

    def check_internet(self, timeout: float = 3.0) -> bool:
        try:
            requests.get(self.internet_url, timeout=timeout)
            return True
        except Exception:
            try:
                requests.head("https://example.com", timeout=timeout)
                return True
            except Exception:
                return False

    def snapshot(self) -> SystemSnapshot:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        gpu, gpu_mem = self._gpu_stats()
        load = None
        try:
            load = psutil.getloadavg()
        except (AttributeError, OSError):
            pass
        return SystemSnapshot(
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_percent=vm.percent,
            ram_used_mb=vm.used / (1024 * 1024),
            ram_total_mb=vm.total / (1024 * 1024),
            disk_percent=disk.percent,
            gpu_percent=gpu,
            gpu_memory_percent=gpu_mem,
            internet_ok=self.check_internet(),
            load_avg=load,
        )

    def warnings(self, snap: SystemSnapshot | None = None) -> list[str]:
        snap = snap or self.snapshot()
        msgs: list[str] = []
        if snap.cpu_percent >= self.cpu_warn:
            msgs.append(f"CPU high: {snap.cpu_percent:.1f}%")
        if snap.ram_percent >= self.ram_warn:
            msgs.append(f"RAM high: {snap.ram_percent:.1f}%")
        if snap.gpu_percent is not None and snap.gpu_percent >= self.gpu_warn:
            msgs.append(f"GPU high: {snap.gpu_percent:.1f}%")
        if not snap.internet_ok:
            msgs.append("Internet connectivity lost")
        return msgs
