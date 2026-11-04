"""START/STOP orchestration: engine + emulators + dashboard, no duplicate processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from centbot.runtime_paths import install_root
from centbot.windows.avd import AVD_NAMES, list_avds, plan_emulator_count, wait_for_boot


def _root():
    return install_root()


def _pid_file():
    return _root() / "data" / "centbot.pid"


def _state_file():
    return _root() / "data" / "runtime" / "launcher_state.json"


# Back-compat aliases (evaluated at call sites via helpers below)
PID_FILE = None  # use _pid_file()
STATE_FILE = None


def _write_state(data: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _read_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def setup_incomplete() -> bool:
    """Incomplete only when durable config/local.yaml is missing (next to exe)."""
    return not (_root() / "config" / "local.yaml").exists()


def _pid_alive(pid: int) -> bool:
    """True if process exists. On Windows prefer tasklist — os.kill(pid,0) is unreliable after crashes."""
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return str(pid) in out and "No tasks" not in out and "INFO:" not in out
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def already_running() -> bool:
    pid_file = _pid_file()
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    if _pid_alive(pid):
        return True
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
    return False


def clear_stale_runtime() -> dict[str, Any]:
    """Drop dead pid / unlock start when previous engine crashed."""
    cleared = False
    pid_file = _pid_file()
    if pid_file.exists() and not already_running():
        cleared = True
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass
    return {"cleared_stale_pid": cleared, "running": already_running()}


def start_emulators(
    *,
    adb: str = "adb",
    emulator: str = "emulator",
    count: int | None = None,
    wait_boot: bool = True,
    boot_timeout_s: float = 120.0,
) -> dict[str, Any]:
    plan = plan_emulator_count()
    n = count if count is not None else int(plan["recommended"])
    names = AVD_NAMES[:n]
    try:
        from centbot.android.adb import ensure_server

        ensure_server(adb)
    except Exception:  # noqa: BLE001
        pass
    try:
        present = set(list_avds(emulator))
    except Exception as exc:  # noqa: BLE001
        return {
            "planned": names,
            "started": [],
            "boots": [],
            "devices": [],
            "plan": plan,
            "ok": False,
            "skipped": True,
            "error": f"list_avds_failed:{exc}",
        }
    if not present.intersection(names):
        # No CENTBOT AVDs — do not sleep/wait_for_boot (that made START appear hung)
        return {
            "planned": names,
            "started": [{"avd": n, "ok": False, "error": "avd_missing"} for n in names],
            "boots": [],
            "devices": [],
            "plan": plan,
            "ok": False,
            "skipped": True,
            "reason": "no_centbot_avds",
            "hint": "Run INSTALL_ANDROID.bat to create CENTBOT_ANDROID_01..04",
        }
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
    boots: list[dict[str, Any]] = []
    time.sleep(2)
    try:
        from centbot.android.adb import devices, devices_detailed, emulator_avd_name

        serials = devices(adb)
        detailed = devices_detailed(adb)
    except Exception:  # noqa: BLE001
        serials = []
        detailed = []
    if wait_boot:
        # Wait for each newly started CENTBOT AVD (cap total wait)
        per = max(15.0, boot_timeout_s / max(1, len([s for s in started if s.get("ok")])))
        deadline = time.time() + boot_timeout_s
        pending = {s["avd"] for s in started if s.get("ok")}
        seen: set[str] = set()
        while pending and time.time() < deadline:
            try:
                from centbot.android.adb import devices as _devices
                from centbot.android.adb import emulator_avd_name as _avd

                for serial in _devices(adb):
                    if not str(serial).startswith("emulator-"):
                        continue
                    avd = _avd(adb, serial)
                    if avd and avd in pending and serial not in seen:
                        boot = wait_for_boot(adb, serial=serial, timeout_s=min(per, max(5.0, deadline - time.time())))
                        boots.append({**boot, "avd": avd})
                        seen.add(serial)
                        if boot.get("ok"):
                            pending.discard(avd)
            except Exception:  # noqa: BLE001
                pass
            if pending:
                time.sleep(2)
        for avd in list(pending):
            boots.append({"ok": False, "error": "boot_timeout", "avd": avd})
    return {
        "planned": names,
        "started": started,
        "boots": boots,
        "devices": serials,
        "devices_detailed": detailed,
        "plan": plan,
        "ok": any(s.get("ok") for s in started),
    }


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
            "pid_file": str(_pid_file()),
            "dashboard": url,
            "hint": "Use STOP.bat / CENTBOT.exe --stop, then start again",
        }
    root = _root()
    if (root / "data" / "EMERGENCY_STOP").exists():
        return {"ok": False, "error": "emergency_stop_active"}

    from centbot.core.config import Config
    from centbot.dashboard.portutil import wait_for_port

    cfg = Config()
    preferred = int(cfg.get("dashboard.port", 8787) or 8787)
    host = str(cfg.get("dashboard.host", "127.0.0.1") or "127.0.0.1")

    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = open(log_dir / "engine.stdout.log", "a", encoding="utf-8")  # noqa: SIM115
    err_log = open(log_dir / "engine.stderr.log", "a", encoding="utf-8")  # noqa: SIM115

    # NEVER launch CENTBOT.exe from launcher — onefile _MEI certifi path breaks live TLS.
    # Always Python -m centbot with durable certs/cacert.pem env.
    from centbot.runtime_paths import bootstrap_runtime, durable_cacert_path

    bootstrap_runtime()
    ca = durable_cacert_path() or (root / "certs" / "cacert.pem")
    cmd = [sys.executable, "-m", "centbot"]
    if mode:
        cmd += ["--mode", mode]
    env = os.environ.copy()
    env["CENTBOT_LAUNCHED_BY"] = "START.bat"
    env["CENTBOT_ROOT"] = str(root)
    env["CENTBOT_USE_EXE"] = "0"
    if ca and Path(ca).is_file():
        env["SSL_CERT_FILE"] = str(ca)
        env["REQUESTS_CA_BUNDLE"] = str(ca)
        env["CURL_CA_BUNDLE"] = str(ca)
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
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
    # Short wait — panel must open fast; heavy work (PoW/integrations) is async after bind
    deadline = time.time() + 18
    while time.time() < deadline:
        dash = read_dashboard_state()
        port = int(dash.get("port") or preferred)
        probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host
        if wait_for_port(probe_host, port, timeout_s=0.4, interval_s=0.15):
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
        time.sleep(0.25)

    if open_dashboard:
        # Open even if still warming — user sees the panel instead of a frozen START window
        _open_browser(url)
    alive = proc.poll() is None
    return {
        "ok": ready or alive,
        "pid": proc.pid,
        "dashboard": url,
        "dashboard_ready": ready,
        "hint": None
        if ready
        else "Dashboard still starting — browser opened to default URL; see logs/engine.stderr.log if blank",
    }


def stop_engine() -> dict[str, Any]:
    pid_file = _pid_file()
    result: dict[str, Any] = {"pid_file": str(pid_file)}
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
            result["killed_pid"] = pid
        except (ValueError, OSError) as exc:
            result["error"] = str(exc)
        try:
            pid_file.unlink(missing_ok=True)
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
    dash_state = _root() / "data" / "runtime" / "dashboard.json"
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
    # Env: CENTBOT_START_EMULATORS=1 forces ON (wins over skip); =0 forces OFF
    env_emu = str(os.environ.get("CENTBOT_START_EMULATORS") or "").strip().lower()
    if env_emu in {"1", "true", "yes"}:
        skip_emulators = False
    elif env_emu in {"0", "false", "no"}:
        skip_emulators = True
    android_on = bool(config.get("android.enabled", True))
    if skip_emulators:
        out["emulators"] = {
            "ok": True,
            "skipped": True,
            "reason": "skip_emulators",
            "hint": "Emulators skipped. Set CENTBOT_START_EMULATORS=1 or pass --with-emulators.",
        }
    elif not skip_emulators and android_on:
        try:
            from centbot.windows.android_sdk import ensure_path_env, resolve_sdk_tools

            _tools = ensure_path_env(resolve_sdk_tools())
        except Exception:  # noqa: BLE001
            _tools = {}
        count = int(config.get("android.max_emulators", 4) or 4)
        emu = start_emulators(
            adb=str(config.get("android.adb_path") or _tools.get("adb") or "adb"),
            emulator=str(config.get("android.emulator_path") or _tools.get("emulator") or "emulator"),
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
