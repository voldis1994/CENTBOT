"""START/STOP orchestration: engine + emulators + dashboard, no duplicate processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from centbot.core.config import ROOT
from centbot.windows.avd import AVD_NAMES, list_avds, plan_emulator_count, wait_for_boot
from centbot.windows.install_state import SetupProgress

PID_FILE = ROOT / "data" / "centbot.pid"
STATE_FILE = ROOT / "data" / "runtime" / "launcher_state.json"


def _write_state(data: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def setup_incomplete() -> bool:
    return not SetupProgress().is_setup_complete() and not (ROOT / "config" / "local.yaml").exists()


def already_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_emulators(*, adb: str = "adb", emulator: str = "emulator", count: int | None = None) -> dict[str, Any]:
    plan = plan_emulator_count()
    n = count if count is not None else int(plan["recommended"])
    names = AVD_NAMES[:n]
    present = set(list_avds(emulator))
    started: list[dict[str, Any]] = []
    for name in names:
        if name not in present:
            started.append({"avd": name, "ok": False, "error": "avd_missing"})
            continue
        try:
            proc = subprocess.Popen(
                [emulator, "-avd", name, "-no-audio", "-no-boot-anim", "-gpu", "auto"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            started.append({"avd": name, "ok": True, "pid": proc.pid})
        except OSError as exc:
            started.append({"avd": name, "ok": False, "error": str(exc)})
    # Wait for devices
    boots: list[dict[str, Any]] = []
    time.sleep(3)
    try:
        from centbot.android.adb import devices

        serials = devices(adb)
    except Exception:  # noqa: BLE001
        serials = []
    for i, serial in enumerate(serials[:n]):
        boots.append(wait_for_boot(adb, serial=serial, timeout_s=120))
    return {"planned": names, "started": started, "boots": boots, "devices": serials, "plan": plan}


def stop_centbot_emulators(*, adb: str = "adb") -> dict[str, Any]:
    """Stop only emulators that look like CENTBOT AVDs / emulator consoles."""
    killed: list[str] = []
    try:
        from centbot.android.adb import devices

        for serial in devices(adb):
            if serial.startswith("emulator-"):
                subprocess.run([adb, "-s", serial, "emu", "kill"], capture_output=True, timeout=20, check=False)
                killed.append(serial)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "killed": killed}
    return {"ok": True, "killed": killed}


def start_engine(*, mode: str | None = None, open_dashboard: bool = True) -> dict[str, Any]:
    if already_running():
        return {"ok": False, "error": "already_running", "pid_file": str(PID_FILE)}
    if (ROOT / "data" / "EMERGENCY_STOP").exists():
        return {"ok": False, "error": "emergency_stop_active"}
    cmd = [sys.executable, "-m", "centbot"]
    if mode:
        cmd += ["--mode", mode]
    env = os.environ.copy()
    env["CENTBOT_LAUNCHED_BY"] = "START.bat"
    # Detached on Windows via START.bat; here we spawn subprocess
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=not sys.platform.startswith("win"),
    )
    state = {"engine_pid": proc.pid, "started_at": time.time(), "open_dashboard": open_dashboard}
    _write_state(state)
    dashboard = "http://127.0.0.1:8787/"
    if open_dashboard:
        _open_browser(dashboard)
    return {"ok": True, "pid": proc.pid, "dashboard": dashboard}


def stop_engine() -> dict[str, Any]:
    result: dict[str, Any] = {"pid_file": str(PID_FILE)}
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
            result["killed_pid"] = pid
        except (ValueError, OSError) as exc:
            result["error"] = str(exc)
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    emu = stop_centbot_emulators()
    result["emulators"] = emu
    state = _read_state()
    state["stopped_at"] = time.time()
    _write_state(state)
    result["ok"] = True
    return result


def _open_browser(url: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
    except OSError:
        pass


def full_start(*, skip_emulators: bool = False) -> dict[str, Any]:
    if setup_incomplete():
        return {"ok": False, "error": "setup_incomplete", "action": "run_SETUP.bat"}
    out: dict[str, Any] = {}
    if not skip_emulators:
        out["emulators"] = start_emulators()
    out["engine"] = start_engine(open_dashboard=True)
    out["ok"] = bool(out["engine"].get("ok"))
    return out
