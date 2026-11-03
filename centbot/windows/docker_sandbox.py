"""Ensure Docker Desktop is usable as the CENTBOT sandbox backend on Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_IMAGE = os.environ.get("CENTBOT_SANDBOX_IMAGE", "python:3.12-slim")


def docker_bin() -> str | None:
    return shutil.which("docker") or shutil.which("podman")


def docker_info() -> dict[str, Any]:
    exe = docker_bin()
    if not exe:
        return {"ok": False, "error": "docker_not_on_path", "hint_lv": "Docker nav PATH — atver Docker Desktop un jaunu CMD."}
    try:
        proc = subprocess.run([exe, "info"], capture_output=True, text=True, timeout=45)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-400:]
            return {
                "ok": False,
                "error": "daemon_not_running",
                "detail": err,
                "exe": exe,
                "hint_lv": "Docker Desktop nav palaists — atver aplikāciju, pagaidi 'Engine running', tad START.bat.",
            }
        return {"ok": True, "exe": exe, "runtime": Path(exe).stem}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "exe": exe}


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


def pull_image(image: str | None = None) -> dict[str, Any]:
    exe = docker_bin()
    if not exe:
        return {"ok": False, "error": "docker_not_on_path"}
    img = image or DEFAULT_IMAGE
    if image_present(img):
        return {"ok": True, "skipped": True, "image": img}
    try:
        proc = subprocess.run(
            [exe, "pull", img],
            capture_output=True,
            text=True,
            timeout=900,
        )
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
            timeout=120,
        )
        out = proc.stdout or ""
        return {
            "ok": proc.returncode == 0 and "centbot-docker-ok" in out,
            "stdout": out[-500:],
            "stderr": (proc.stderr or "")[-500:],
            "image": img,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def ensure_docker_sandbox(*, pull: bool = True) -> dict[str, Any]:
    """Probe daemon, pull image, smoke-test. Sets env for START when OK."""
    info = docker_info()
    steps: list[dict[str, Any]] = [{"step": "info", "result": info}]
    if not info.get("ok"):
        return {
            "ok": False,
            "docker": False,
            "steps": steps,
            "hint_lv": info.get("hint_lv") or "Docker nav gatavs.",
            "require_container": "0",
        }
    if pull:
        pulled = pull_image()
        steps.append({"step": "pull", "result": pulled})
        if not pulled.get("ok"):
            return {
                "ok": False,
                "docker": True,
                "daemon": True,
                "steps": steps,
                "hint_lv": f"Neizdevās docker pull {DEFAULT_IMAGE}. Pārbaudi internetu.",
                "require_container": "0",
            }
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
            "Docker sandbox gatavs — CENTBOT lietos konteineru izolāciju."
            if ok
            else "Docker daemon OK, bet smoke run neizdevās — skaties stderr."
        ),
    }


def write_docker_env(report: dict[str, Any], *, root: Path | None = None) -> Path | None:
    from centbot.runtime_paths import install_root

    base = Path(root) if root else install_root()
    path = base / "data" / "docker.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"CENTBOT_REQUIRE_CONTAINER={report.get('require_container') or '0'}",
        f"CENTBOT_SANDBOX_BACKEND={'docker' if report.get('ok') else 'restrictor_only'}",
        f"CENTBOT_SANDBOX_IMAGE={DEFAULT_IMAGE}",
    ]
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Ensure Docker sandbox for CENTBOT")
    p.add_argument("--status", action="store_true")
    p.add_argument("--no-pull", action="store_true")
    args = p.parse_args(argv)
    if args.status:
        print(json.dumps({"info": docker_info(), "image": image_present()}, indent=2))
        return 0 if docker_info().get("ok") else 1
    report = ensure_docker_sandbox(pull=not args.no_pull)
    env_path = write_docker_env(report)
    report["env_file"] = str(env_path) if env_path else None
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
