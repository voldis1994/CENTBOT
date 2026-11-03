"""Isolated environment for untrusted files and code.

Malicious Python is executed inside a **strict container** when possible
(Docker/Podman, or Linux ``unshare``+chroot). A userspace restrictor still runs
*inside* the container as defense-in-depth, but is never treated as the sole
security boundary.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from centbot.sandbox import container as _container
from centbot.sandbox import restrictor as _restrictor_module


def _write_bootstrap(workdir: Path, script_path: Path) -> Path:
    """Create a launcher that installs restrictions before running the target script."""
    restrictor_src = Path(_restrictor_module.__file__).read_text(encoding="utf-8")
    (workdir / "_centbot_restrictor.py").write_text(restrictor_src, encoding="utf-8")
    # Paths inside container use /work; outside restrictor_only use absolute workdir
    launcher = workdir / "_centbot_launch.py"
    launcher.write_text(
        textwrap.dedent(
            """\
            import os
            import runpy
            import sys
            from pathlib import Path

            # Inside Docker/unshare chroot CENTBOT_SANDBOX_ROOT=/work; otherwise host workdir.
            root = Path(os.environ.get("CENTBOT_SANDBOX_ROOT") or Path(__file__).resolve().parent)
            sys.path.insert(0, str(root))
            import _centbot_restrictor

            _centbot_restrictor.install(str(root))
            script = root / "_run_target.py"
            sys.argv = [str(script)] + sys.argv[1:]
            runpy.run_path(str(script), run_name="__main__")
            """
        ),
        encoding="utf-8",
    )
    # Copy/normalize target as _run_target.py for stable container path
    target = workdir / "_run_target.py"
    if script_path.resolve() != target.resolve():
        target.write_bytes(Path(script_path).read_bytes())
    return launcher


def _restrictor_only_command(launcher: Path) -> list[str]:
    return [sys.executable, "-I", str(launcher)]


def run_python_isolated(
    code: str | None = None,
    script_path: Path | None = None,
    workdir: Path | None = None,
    timeout: float = 30.0,
    extra_env: dict[str, str] | None = None,
    *,
    require_container: bool | None = None,
) -> dict[str, Any]:
    """Run Python confined to ``workdir`` inside a container when available."""
    workdir = Path(workdir or tempfile.mkdtemp(prefix="centbot-sandbox-"))
    workdir.mkdir(parents=True, exist_ok=True)
    if script_path is None:
        script_path = workdir / "_run.py"
        script_path.write_text(code or "print('ok')", encoding="utf-8")
    else:
        script_path = Path(script_path)
        try:
            script_path.resolve().relative_to(workdir.resolve())
        except ValueError:
            dest = workdir / script_path.name
            dest.write_bytes(script_path.read_bytes())
            script_path = dest

    launcher = _write_bootstrap(workdir, script_path)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "TEMP": str(workdir),
        "TMP": str(workdir),
        "PYTHONPATH": str(workdir),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CENTBOT_SANDBOX": "1",
        # Overwritten to /work by container backends
        "CENTBOT_SANDBOX_ROOT": str(workdir.resolve()),
    }
    if extra_env:
        for k, v in extra_env.items():
            if k.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PRIVATE")):
                continue
            env[k] = v

    if require_container is None:
        require_container = os.environ.get("CENTBOT_REQUIRE_CONTAINER", "1") not in {"0", "false", "False"}

    preferred = os.environ.get("CENTBOT_SANDBOX_BACKEND")
    container_result = _container.run_containerized(
        launcher=launcher,
        workdir=workdir,
        timeout=timeout,
        env=env,
        preferred=preferred,
    )
    if container_result.get("container"):
        return container_result
    if require_container:
        return {
            **container_result,
            "ok": False,
            "error": container_result.get("error") or "container_required",
            "hint": "Install Docker/Podman or enable unshare user namespaces; "
            "set CENTBOT_REQUIRE_CONTAINER=0 only for non-adversarial local debug.",
        }

    # Explicit insecure fallback for debug only
    cmd = _restrictor_only_command(launcher)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:],
            "workdir": str(workdir),
            "command": cmd[:3],
            "restricted": True,
            "container": False,
            "backend": "restrictor_only",
            "insecure_fallback": True,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "timeout",
            "workdir": str(workdir),
            "backend": "restrictor_only",
            "insecure_fallback": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "workdir": str(workdir),
            "backend": "restrictor_only",
            "insecure_fallback": True,
        }


def isolate_file(src: Path, sandbox_root: Path) -> Path:
    """Copy a file into the sandbox as read-only when possible."""
    sandbox_root.mkdir(parents=True, exist_ok=True)
    dest = sandbox_root / Path(src).name
    dest.write_bytes(Path(src).read_bytes())
    try:
        dest.chmod(0o444)
    except OSError:
        pass
    return dest


def sandbox_available() -> bool:
    """Health check: container backend runs print and blocks network."""
    return bool(sandbox_diagnose().get("ok"))


def sandbox_diagnose() -> dict[str, Any]:
    """Detailed sandbox readiness (used by engine alerts + Windows Docker helper)."""
    backends = _container.available_backends()
    selected = _container.select_backend()
    out: dict[str, Any] = {
        "ok": False,
        "selected": selected,
        "available": backends,
        "docker_on_path": bool(backends.get("docker") or backends.get("podman")),
    }
    if not (backends.get("docker") or backends.get("podman") or backends.get("unshare_container")):
        out["error"] = "no_container_backend"
        out["hint_lv"] = "Docker/Podman nav PATH. Palaid Docker Desktop un jaunu CMD."
        return out
    # Prefer requiring container for the probe even if START set REQUIRE=0
    old = os.environ.get("CENTBOT_REQUIRE_CONTAINER")
    os.environ["CENTBOT_REQUIRE_CONTAINER"] = "1"
    try:
        result = run_python_isolated(code="print('centbot-sandbox-ok')", timeout=60, require_container=True)
    finally:
        if old is None:
            os.environ.pop("CENTBOT_REQUIRE_CONTAINER", None)
        else:
            os.environ["CENTBOT_REQUIRE_CONTAINER"] = old
    out["probe"] = {
        "ok": result.get("ok"),
        "container": result.get("container"),
        "backend": result.get("backend"),
        "error": result.get("error"),
        "stderr": (result.get("stderr") or "")[:300],
    }
    if not (result.get("ok") and "centbot-sandbox-ok" in (result.get("stdout") or "")):
        out["error"] = result.get("error") or "probe_failed"
        if out["docker_on_path"]:
            out["hint_lv"] = (
                "Docker ir instalēts, bet sandbox run neizdevās — "
                "pārliecinies, ka Docker Desktop Engine ir Running, tad palaid: "
                "python -m centbot.windows.docker_sandbox"
            )
        else:
            out["hint_lv"] = "Konteinera backend nav pieejams."
        return out
    if not result.get("container"):
        out["error"] = "not_containerized"
        out["hint_lv"] = "Sandbox nestrādā konteinerī."
        return out
    net = run_python_isolated(code="import socket", timeout=30, require_container=True)
    out["network_blocked"] = not bool(net.get("ok"))
    if net.get("ok"):
        out["error"] = "network_not_blocked"
        out["hint_lv"] = "Sandbox nebloķē tīklu."
        return out
    out["ok"] = True
    out["hint_lv"] = f"Sandbox OK ({result.get('backend')})"
    return out


def sandbox_backend_info() -> dict[str, Any]:
    diag = sandbox_diagnose()
    return {
        "selected": diag.get("selected") or _container.select_backend(),
        "available": diag.get("available") or _container.available_backends(),
        "ok": bool(diag.get("ok")),
        "error": diag.get("error"),
        "hint_lv": diag.get("hint_lv"),
        "docker_on_path": diag.get("docker_on_path"),
    }
