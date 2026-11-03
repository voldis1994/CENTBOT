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
    """Incomplete only when config/local.yaml is missing.

    Docker/Android gaps must NOT block START — live engine runs so platform
    claim errors are visible; emulator/sandbox lanes skip with warnings.
    """
    return not (ROOT / "config" / "local.yaml").exists()


def already_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        # Stale pid file — clear so port/address is not "owned" forever
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def clear_stale_runtime() -> dict[str, Any]:
    """Drop dead pid / unlock start when previous engine crashed."""
    cleared = False
    if PID_FILE.exists() and not already_running():
        cleared = True
    return {"cleared_stale_pid": cleared, "running": already_running()}


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


def _emulator_avd_name(adb: str, serial: str) -> str | None:
    try:
        out = subprocess.check_output(
            [adb, "-s", serial, "emu", "avd", "name"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        )
        # First non-empty line is the AVD name; ignore "OK"
        for line in out.splitlines():
            name = line.strip()
            if name and name.upper() != "OK":
                return name
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def stop_centbot_emulators(*, adb: str = "adb") -> dict[str, Any]:
    """Stop ONLY emulators whose AVD name is CENTBOT_ANDROID_* — never foreign AVDs."""
    from centbot.windows.avd import AVD_NAMES

    killed: list[str] = []
    skipped: list[dict[str, str]] = []
    try:
        from centbot.android.adb import devices

        for serial in devices(adb):
            if not str(serial).startswith("emulator-"):
                continue
            avd = _emulator_avd_name(adb, serial)
            if avd and avd in AVD_NAMES:
                subprocess.run([adb, "-s", serial, "emu", "kill"], capture_output=True, timeout=20, check=False)
                killed.append(f"{serial}:{avd}")
            else:
                skipped.append({"serial": serial, "avd": avd or "unknown", "reason": "not_centbot_avd"})
        # Also terminate tracked Popen PIDs from launcher state
        state = _read_state()
        for item in state.get("emulator_pids") or []:
            try:
                pid = int(item.get("pid"))
                if sys.platform.startswith("win"):
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
                else:
                    os.kill(pid, 15)
                killed.append(f"pid:{pid}")
            except (TypeError, ValueError, OSError):
                continue
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "killed": killed, "skipped": skipped}
    return {"ok": True, "killed": killed, "skipped": skipped}


def start_engine(*, mode: str | None = None, open_dashboard: bool = True) -> dict[str, Any]:
    clear_stale_runtime()
    if already_running():
        from centbot.dashboard.app import read_dashboard_state

        state = read_dashboard_state()
        url = state.get("url") or "http://127.0.0.1:8787/"
        if open_dashboard:
            _open_browser(str(url))
        return {
            "ok": False,
            "error": "already_running",
            "pid_file": str(PID_FILE),
            "dashboard": url,
            "hint": "Use STOP.bat / CENTBOT.exe --stop, then start again",
        }
    if (ROOT / "data" / "EMERGENCY_STOP").exists():
        return {"ok": False, "error": "emergency_stop_active"}

    from centbot.core.config import Config
    from centbot.dashboard.portutil import wait_for_port

    cfg = Config()
    preferred = int(cfg.get("dashboard.port", 8787) or 8787)
    host = str(cfg.get("dashboard.host", "127.0.0.1") or "127.0.0.1")

    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = open(log_dir / "engine.stdout.log", "a", encoding="utf-8")  # noqa: SIM115
    err_log = open(log_dir / "engine.stderr.log", "a", encoding="utf-8")  # noqa: SIM115

    # Prefer packaged exe when present (same folder as repo root)
    exe = ROOT / "CENTBOT.exe"
    if exe.exists() and sys.platform.startswith("win"):
        cmd = [str(exe), "--engine"]
    else:
        cmd = [sys.executable, "-m", "centbot"]
    if mode:
        cmd += ["--mode", mode]
    env = os.environ.copy()
    env["CENTBOT_LAUNCHED_BY"] = "START.bat"
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=out_log,
        stderr=err_log,
        creationflags=creationflags,
        start_new_session=not sys.platform.startswith("win"),
    )
    state = {
        "engine_pid": proc.pid,
        "started_at": time.time(),
        "open_dashboard": open_dashboard,
        "preferred_port": preferred,
    }
    _write_state(state)

    # Wait until dashboard actually listens — fixes ERR_CONNECTION_REFUSED from early browser open
    from centbot.dashboard.app import read_dashboard_state

    ready = False
    url = f"http://127.0.0.1:{preferred}/"
    deadline = time.time() + 50
    while time.time() < deadline:
        dash = read_dashboard_state()
        port = int(dash.get("port") or preferred)
        probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host
        if wait_for_port(probe_host, port, timeout_s=0.6, interval_s=0.2):
            url = str(dash.get("url") or f"http://{probe_host}:{port}/")
            ready = True
            state["dashboard"] = url
            state["port"] = port
            state["bumped"] = bool(dash.get("bumped"))
            _write_state(state)
            break
        # Engine died before binding
        if proc.poll() is not None:
            break
        time.sleep(0.4)

    if open_dashboard and ready:
        _open_browser(url)
    return {
        "ok": ready or proc.poll() is None,
        "pid": proc.pid,
        "dashboard": url,
        "dashboard_ready": ready,
        "hint": None
        if ready
        else "Dashboard not reachable yet — check logs/engine.stderr.log; port may still be starting",
    }


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
    # Also kill launcher-tracked engine pid if present
    state = _read_state()
    tracked = state.get("engine_pid")
    if tracked and tracked != result.get("killed_pid"):
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(tracked), "/T", "/F"], capture_output=True, check=False)
            else:
                os.kill(int(tracked), 15)
            result["killed_tracked_pid"] = tracked
        except (TypeError, ValueError, OSError):
            pass
    emu = stop_centbot_emulators()
    result["emulators"] = emu
    state["stopped_at"] = time.time()
    _write_state(state)
    dash_state = ROOT / "data" / "runtime" / "dashboard.json"
    try:
        dash_state.unlink(missing_ok=True)
    except OSError:
        pass
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
    from centbot.core.config import Config
    from centbot.core.consistency import audit_config

    config = Config()
    audit = audit_config(config)
    out: dict[str, Any] = {"consistency": audit}
    android_on = bool(config.get("android.enabled", True))
    if not skip_emulators and android_on:
        count = int(config.get("android.max_emulators", 4) or 4)
        emu = start_emulators(
            adb=str(config.get("android.adb_path", "adb")),
            emulator=str(config.get("android.emulator_path", "emulator")),
            count=count,
        )
        out["emulators"] = emu
        # Persist CENTBOT emulator PIDs so STOP only kills ours
        state = _read_state()
        state["emulator_pids"] = [
            {"avd": r.get("avd"), "pid": r.get("pid")} for r in (emu.get("started") or []) if r.get("ok") and r.get("pid")
        ]
        _write_state(state)
        # Missing AVDs are warnings — engine still starts for live PC claims
        if any(not r.get("ok") for r in (emu.get("started") or [])):
            out["warning_android"] = "some_avds_missing_or_failed_engine_still_starting"
    elif not android_on:
        out["emulators"] = {
            "ok": True,
            "skipped": True,
            "reason": "android.enabled_is_false",
            "hint": "Set android.enabled: true in config/local.yaml",
        }
    # Live: never refuse start — print consistency so real errors are visible
    if config.is_live() and not audit.get("ready_for_live"):
        out["warning"] = "live_partial_readiness"
        out["consistency"] = audit
    out["engine"] = start_engine(open_dashboard=True)
    out["ok"] = bool(out["engine"].get("ok"))
    return out
