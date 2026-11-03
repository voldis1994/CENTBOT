"""Ensure Docker Desktop is usable as the CENTBOT sandbox backend on Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_IMAGE = os.environ.get("CENTBOT_SANDBOX_IMAGE", "python:3.12-slim")


def docker_bin() -> str | None:
    return shutil.which("docker") or shutil.which("podman")


def start_docker_desktop() -> dict[str, Any]:
    """Best-effort launch Docker Desktop on Windows."""
    if not sys.platform.startswith("win"):
        return {"ok": False, "skipped": True, "reason": "not_windows"}
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Docker" / "Docker" / "Docker Desktop.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "Docker Desktop.exe",
    ]
    for exe in candidates:
        if exe.is_file():
            try:
                subprocess.Popen(
                    [str(exe)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(exe.parent),
                )
                return {"ok": True, "started": str(exe)}
            except OSError as exc:
                return {"ok": False, "error": str(exc), "path": str(exe)}
    return {"ok": False, "error": "docker_desktop_exe_not_found"}


def docker_info() -> dict[str, Any]:
    exe = docker_bin()
    if not exe:
        return {"ok": False, "error": "docker_not_on_path", "hint_lv": "Docker nav PATH — atver Docker Desktop un JAUNU CMD."}
    try:
        proc = subprocess.run([exe, "info"], capture_output=True, text=True, timeout=45)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-400:]
            return {
                "ok": False,
                "error": "daemon_not_running",
                "detail": err,
                "exe": exe,
                "hint_lv": "Docker Desktop Engine nav Running — atver aplikāciju un gaidi zaļo statusu.",
            }
        return {"ok": True, "exe": exe, "runtime": Path(exe).stem}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "exe": exe}


def wait_for_daemon(*, attempts: int = 24, delay_sec: float = 5.0) -> dict[str, Any]:
    """Wait until `docker info` succeeds (Desktop boot can take 1–2 min)."""
    last: dict[str, Any] = {}
    for i in range(attempts):
        last = docker_info()
        if last.get("ok"):
            last["waited_sec"] = int(i * delay_sec)
            return last
        time.sleep(delay_sec)
    last["waited_sec"] = int(attempts * delay_sec)
    return last


def image_present(image: str | None = None) -> bool:
    exe = docker_bin()
    if not exe:
        return False
    img = image or DEFAULT_IMAGE
    try:
        proc = subprocess.run(
            [exe, "image", "inspect", img],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode == 0
    except Exception:
        return False


def pull_image(image: str | None = None, *, visible: bool = True) -> dict[str, Any]:
    exe = docker_bin()
    if not exe:
        return {"ok": False, "error": "docker_not_on_path"}
    img = image or DEFAULT_IMAGE
    if image_present(img):
        return {"ok": True, "skipped": True, "image": img}
    try:
        # Visible pull so Windows user sees progress (capture hides everything)
        if visible:
            proc = subprocess.run([exe, "pull", img], timeout=900)
            return {"ok": proc.returncode == 0, "image": img, "visible": True}
        proc = subprocess.run([exe, "pull", img], capture_output=True, text=True, timeout=900)
        return {
            "ok": proc.returncode == 0,
            "image": img,
            "stdout": (proc.stdout or "")[-500:],
            "stderr": (proc.stderr or "")[-500:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "image": img}


def smoke_run() -> dict[str, Any]:
    """Minimal docker run with network=none to prove sandbox works."""
    exe = docker_bin()
    if not exe:
        return {"ok": False, "error": "docker_not_on_path"}
    img = DEFAULT_IMAGE
    try:
        proc = subprocess.run(
            [
                exe,
                "run",
                "--rm",
                "--network=none",
                img,
                "python",
                "-c",
                "print('centbot-docker-ok')",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        out = proc.stdout or ""
        return {
            "ok": proc.returncode == 0 and "centbot-docker-ok" in out,
            "stdout": out[-500:],
            "stderr": (proc.stderr or "")[-500:],
            "image": img,
            "code": proc.returncode,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def ensure_docker_sandbox(*, pull: bool = True, autostart: bool = True) -> dict[str, Any]:
    """Probe daemon (start Desktop if needed), pull image, smoke-test."""
    steps: list[dict[str, Any]] = []
    info = docker_info()
    steps.append({"step": "info", "result": dict(info)})

    if not info.get("ok") and docker_bin() and autostart and sys.platform.startswith("win"):
        started = start_docker_desktop()
        steps.append({"step": "start_desktop", "result": started})
        print("[CENTBOT] Starting Docker Desktop — waiting for Engine...")
        info = wait_for_daemon(attempts=24, delay_sec=5.0)
        steps.append({"step": "wait_daemon", "result": dict(info)})

    if not info.get("ok"):
        if not docker_bin():
            # Try starting Desktop even when docker.exe not yet on PATH of this process
            if autostart and sys.platform.startswith("win"):
                started = start_docker_desktop()
                steps.append({"step": "start_desktop_no_path", "result": started})
        return {
            "ok": False,
            "docker": bool(docker_bin()),
            "steps": steps,
            "hint_lv": info.get("hint_lv")
            or "Docker nav gatavs. Atver Docker Desktop, gaidi Engine Running, atver JAUNU CMD, ENSURE_DOCKER.bat.",
            "require_container": "0",
        }

    if pull:
        print(f"[CENTBOT] docker pull {DEFAULT_IMAGE} ...")
        pulled = pull_image(visible=True)
        steps.append({"step": "pull", "result": pulled})
        if not pulled.get("ok"):
            return {
                "ok": False,
                "docker": True,
                "daemon": True,
                "steps": steps,
                "hint_lv": f"docker pull {DEFAULT_IMAGE} neizdevās — internets/firewall. LIVE tomēr strādā ar restrictor.",
                "require_container": "0",
            }

    print("[CENTBOT] Smoke test: docker run --network=none ...")
    smoke = smoke_run()
    steps.append({"step": "smoke", "result": smoke})
    ok = bool(smoke.get("ok"))
    if ok:
        os.environ["CENTBOT_REQUIRE_CONTAINER"] = "1"
        os.environ.setdefault("CENTBOT_SANDBOX_BACKEND", info.get("runtime") or "docker")
        os.environ.setdefault("CENTBOT_SANDBOX_IMAGE", DEFAULT_IMAGE)
    return {
        "ok": ok,
        "docker": True,
        "daemon": True,
        "image": DEFAULT_IMAGE,
        "steps": steps,
        "require_container": "1" if ok else "0",
        "hint_lv": (
            "Docker sandbox gatavs — START.bat lietos konteineru."
            if ok
            else "Daemon OK, bet smoke neizdevās — LIVE ar restrictor. Skaties smoke stderr."
        ),
    }


def write_docker_env(report: dict[str, Any], *, root: Path | None = None) -> Path | None:
    from centbot.runtime_paths import install_root

    base = Path(root) if root else Path(os.environ.get("CENTBOT_ROOT") or install_root())
    # Prefer cwd install
    cwd = Path.cwd()
    if (cwd / "START.bat").exists():
        base = cwd
    path = base / "data" / "docker.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"CENTBOT_REQUIRE_CONTAINER={report.get('require_container') or '0'}",
        f"CENTBOT_SANDBOX_BACKEND={'docker' if report.get('ok') else 'restrictor_only'}",
        f"CENTBOT_SANDBOX_IMAGE={DEFAULT_IMAGE}",
    ]
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return path
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Ensure Docker sandbox for CENTBOT")
    p.add_argument("--status", action="store_true")
    p.add_argument("--no-pull", action="store_true")
    p.add_argument("--no-autostart", action="store_true")
    p.add_argument("--soft", action="store_true", help="Exit 0 even if Docker not ready")
    args = p.parse_args(argv)
    if args.status:
        print(json.dumps({"info": docker_info(), "image": image_present()}, indent=2))
        return 0 if docker_info().get("ok") else 1
    report = ensure_docker_sandbox(pull=not args.no_pull, autostart=not args.no_autostart)
    if not report.get("ok"):
        report["require_container"] = "0"
    env_path = write_docker_env(report)
    report["env_file"] = str(env_path) if env_path else None
    print(json.dumps(report, indent=2, default=str))
    print(report.get("hint_lv") or "")
    if report.get("ok"):
        return 0
    return 0 if args.soft else 1


if __name__ == "__main__":
    raise SystemExit(main())
