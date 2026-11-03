"""Strict process isolation via Docker (preferred) or Linux namespace container.

Userspace import/FS restrictors alone are not a security boundary against malicious
Python. This module runs untrusted code inside a real container when possible:

1. Docker / Podman — ``--network=none --read-only`` with workdir bind-mount
2. ``unshare`` user+mount+pid+net + ``chroot`` — Linux container without a daemon

Windows hosts should use an external Windows VM / Hyper-V sandbox (configured via
``CENTBOT_SANDBOX_BACKEND=windows_vm``); this module refuses to pretend a userspace
restrictor is enough there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _which_container_runtime() -> tuple[str, str] | None:
    for name in ("docker", "podman"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


def _probe_unshare_container() -> bool:
    unshare = shutil.which("unshare")
    chroot = shutil.which("chroot")
    if not unshare or not chroot:
        return False
    try:
        probe = subprocess.run(
            [unshare, "-r", "-n", "-m", "-p", "-f", "--", "true"],
            capture_output=True,
            timeout=3,
        )
        return probe.returncode == 0
    except Exception:
        return False


def available_backends() -> dict[str, bool]:
    docker = _which_container_runtime() is not None
    return {
        "docker": docker,
        "podman": shutil.which("podman") is not None,
        "unshare_container": _probe_unshare_container(),
        "windows_vm": False,  # external; never auto-claimed on Linux
    }


def select_backend(preferred: str | None = None) -> str:
    preferred = (preferred or os.environ.get("CENTBOT_SANDBOX_BACKEND") or "auto").lower()
    backends = available_backends()
    if preferred == "windows_vm":
        return "windows_vm"
    if preferred in {"docker", "podman"} and backends.get(preferred):
        return preferred
    if preferred == "unshare_container" and backends["unshare_container"]:
        return "unshare_container"
    if preferred == "restrictor_only":
        return "restrictor_only"
    # auto
    if backends["docker"] or backends["podman"]:
        rt = _which_container_runtime()
        return rt[0] if rt else "unshare_container"
    if backends["unshare_container"]:
        return "unshare_container"
    return "restrictor_only"


def _write_entry_script(path: Path) -> Path:
    """Bash entry that builds a chroot rootfs and execs python inside it."""
    # Shebang must start at column 0 (no dedent indent).
    path.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        'ROOT="$1"\n'
        'WORKDIR="$2"\n'
        'PY="$3"\n'
        "shift 3\n"
        "mount --make-rprivate / 2>/dev/null || true\n"
        "for p in /usr /lib /lib64 /bin /sbin /etc; do\n"
        '  [ -e "$p" ] || continue\n'
        '  mkdir -p "$ROOT$p"\n'
        '  mount --bind "$p" "$ROOT$p"\n'
        '  mount -o remount,ro,bind "$ROOT$p" 2>/dev/null || true\n'
        "done\n"
        'mkdir -p "$ROOT/work" "$ROOT/tmp" "$ROOT/proc" "$ROOT/dev" '
        '"$ROOT/home" "$ROOT/var" "$ROOT/opt" "$ROOT/root" '
        '"$ROOT/mnt" "$ROOT/media" "$ROOT/boot" "$ROOT/sys" "$ROOT/run"\n'
        'mount --bind "$WORKDIR" "$ROOT/work"\n'
        'mount -t tmpfs -o size=128m,mode=1777 tmpfs "$ROOT/tmp"\n'
        'mount -t proc proc "$ROOT/proc" 2>/dev/null || true\n'
        "for hide in home var opt root mnt media boot sys run; do\n"
        '  mount -t tmpfs -o size=1m,mode=755 tmpfs "$ROOT/$hide" 2>/dev/null || true\n'
        "done\n"
        "for sens in passwd shadow group gshadow sudoers hostname machine-id; do\n"
        '  if [ -e "$ROOT/etc/$sens" ]; then\n'
        '    mount --bind /dev/null "$ROOT/etc/$sens" 2>/dev/null || true\n'
        "  fi\n"
        "done\n"
        "export HOME=/work TMPDIR=/tmp TEMP=/tmp TMP=/tmp\n"
        "export PYTHONNOUSERSITE=1 CENTBOT_SANDBOX=1 CENTBOT_SANDBOX_ROOT=/work\n"
        "export CENTBOT_SANDBOX_BACKEND=unshare_container\n"
        # Force cwd=/work inside the jail (chroot alone may leave cwd at /)
        'exec chroot "$ROOT" /bin/bash -c \'cd /work && exec "$@"\' bash "$PY" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def run_in_docker(
    *,
    launcher: Path,
    workdir: Path,
    timeout: float,
    env: dict[str, str],
    runtime: str | None = None,
) -> dict[str, Any]:
    rt = _which_container_runtime()
    if runtime:
        path = shutil.which(runtime)
        if not path:
            return {"ok": False, "error": f"runtime_missing:{runtime}", "backend": runtime}
        name, path = runtime, path
    elif rt:
        name, path = rt
    else:
        return {"ok": False, "error": "docker_unavailable", "backend": "docker"}

    image = os.environ.get("CENTBOT_SANDBOX_IMAGE", "python:3.12-slim")
    rel_launcher = launcher.resolve().relative_to(workdir.resolve())
    cmd = [
        path,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "-v",
        f"{workdir.resolve()}:/work:rw",
        "-w",
        "/work",
        "-e",
        "CENTBOT_SANDBOX=1",
        "-e",
        "CENTBOT_SANDBOX_ROOT=/work",
        "-e",
        f"CENTBOT_SANDBOX_BACKEND={name}",
        "-e",
        "PYTHONNOUSERSITE=1",
        "-e",
        "HOME=/work",
        "-e",
        "TMPDIR=/tmp",
        image,
        "python",
        "-I",
        f"/work/{rel_launcher.as_posix()}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **env})
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:],
            "backend": name,
            "workdir": str(workdir),
            "restricted": True,
            "container": True,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "backend": name, "workdir": str(workdir), "container": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "backend": name, "workdir": str(workdir), "container": True}


def run_in_unshare_container(
    *,
    launcher: Path,
    workdir: Path,
    timeout: float,
    env: dict[str, str],
) -> dict[str, Any]:
    unshare = shutil.which("unshare")
    if not unshare or not _probe_unshare_container():
        return {"ok": False, "error": "unshare_container_unavailable", "backend": "unshare_container"}

    root = Path(tempfile.mkdtemp(prefix="centbot-rootfs-"))
    entry = _write_entry_script(workdir / "_centbot_container_entry.sh")
    rel_launcher = launcher.resolve().relative_to(workdir.resolve())
    py = sys.executable
    cmd = [
        unshare,
        "-r",
        "-n",
        "-m",
        "-p",
        "-f",
        "--mount-proc",
        "--kill-child",
        "--",
        str(entry),
        str(root),
        str(workdir.resolve()),
        py,
        "-I",
        f"/work/{rel_launcher.as_posix()}",
    ]
    # Strip host env; pass only sandbox env
    child_env = {k: v for k, v in env.items()}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=child_env)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:],
            "backend": "unshare_container",
            "workdir": str(workdir),
            "restricted": True,
            "container": True,
            "command": cmd[:6],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "timeout",
            "backend": "unshare_container",
            "workdir": str(workdir),
            "container": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "backend": "unshare_container",
            "workdir": str(workdir),
            "container": True,
        }


def run_containerized(
    *,
    launcher: Path,
    workdir: Path,
    timeout: float,
    env: dict[str, str],
    preferred: str | None = None,
) -> dict[str, Any]:
    backend = select_backend(preferred)
    if backend == "windows_vm":
        return {
            "ok": False,
            "error": "windows_vm_required",
            "backend": "windows_vm",
            "hint": "Configure an external Windows VM / Hyper-V sandbox; userspace restrictor is not sufficient.",
        }
    if backend in {"docker", "podman"}:
        result = run_in_docker(launcher=launcher, workdir=workdir, timeout=timeout, env=env, runtime=backend)
        if result.get("ok") or result.get("returncode") is not None:
            return result
        # Fall through if daemon missing mid-flight
    if backend in {"docker", "podman", "unshare_container"} or select_backend("auto") == "unshare_container":
        if available_backends()["unshare_container"]:
            return run_in_unshare_container(launcher=launcher, workdir=workdir, timeout=timeout, env=env)
    return {
        "ok": False,
        "error": "no_strict_container_backend",
        "backend": backend,
        "available": available_backends(),
    }
