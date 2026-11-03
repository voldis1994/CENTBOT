"""Isolated environment for untrusted files and code.

Runs foreign Python under a userspace restrictor (no network imports, FS confined
to the workdir) and, when available, a network-namespaced process via ``unshare -n``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from centbot.sandbox import restrictor as _restrictor_module


def _write_bootstrap(workdir: Path, script_path: Path) -> Path:
    """Create a launcher that installs restrictions before running the target script."""
    restrictor_src = Path(_restrictor_module.__file__).read_text(encoding="utf-8")
    (workdir / "_centbot_restrictor.py").write_text(restrictor_src, encoding="utf-8")
    launcher = workdir / "_centbot_launch.py"
    launcher.write_text(
        textwrap.dedent(
            f"""\
            import runpy
            import sys
            from pathlib import Path
            sys.path.insert(0, r"{workdir}")
            import _centbot_restrictor
            _centbot_restrictor.install(r"{workdir}")
            sys.argv = [r"{script_path}"] + sys.argv[1:]
            runpy.run_path(r"{script_path}", run_name="__main__")
            """
        ),
        encoding="utf-8",
    )
    return launcher


def _build_command(launcher: Path) -> list[str]:
    """Prefer network namespace isolation when unshare is available and permitted."""
    base = [sys.executable, "-I", str(launcher)]
    unshare = shutil.which("unshare")
    if not unshare:
        return base
    # -n: new network namespace (no interfaces except lo if configured; typically no egress)
    # --map-current-user avoids requiring full root on some kernels with user ns
    candidates = [
        [unshare, "-n", "-r", "--", *base],
        [unshare, "-n", "--", *base],
    ]
    for cmd in candidates:
        try:
            probe = subprocess.run(
                [unshare, "-n", "true"] if "-r" not in cmd else [unshare, "-n", "-r", "true"],
                capture_output=True,
                timeout=2,
            )
            if probe.returncode == 0:
                return cmd
        except Exception:
            continue
    return base


def run_python_isolated(
    code: str | None = None,
    script_path: Path | None = None,
    workdir: Path | None = None,
    timeout: float = 30.0,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run Python confined to ``workdir`` without network or host FS access."""
    workdir = Path(workdir or tempfile.mkdtemp(prefix="centbot-sandbox-"))
    workdir.mkdir(parents=True, exist_ok=True)
    if script_path is None:
        script_path = workdir / "_run.py"
        script_path.write_text(code or "print('ok')", encoding="utf-8")
    else:
        script_path = Path(script_path)
        # Ensure script lives inside workdir (copy if needed)
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
        "CENTBOT_SANDBOX_ROOT": str(workdir.resolve()),
    }
    if extra_env:
        # Still strip secrets
        for k, v in extra_env.items():
            if k.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PRIVATE")):
                continue
            env[k] = v

    cmd = _build_command(launcher)
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
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "workdir": str(workdir), "restricted": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "workdir": str(workdir), "restricted": True}


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
    """Health check: restrictor blocks network and allows workdir prints."""
    result = run_python_isolated(code="print('centbot-sandbox-ok')", timeout=10)
    if not (result.get("ok") and "centbot-sandbox-ok" in (result.get("stdout") or "")):
        return False
    # Network must fail inside sandbox
    net = run_python_isolated(code="import socket", timeout=10)
    if net.get("ok"):
        return False
    return True
