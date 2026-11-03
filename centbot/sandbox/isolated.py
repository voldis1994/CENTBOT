"""Isolated environment for untrusted files and code.

Public import path: ``centbot.sandbox.isolated`` (also re-exported from
``centbot.sandbox``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def run_python_isolated(
    code: str | None = None,
    script_path: Path | None = None,
    workdir: Path | None = None,
    timeout: float = 30.0,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run Python in a subprocess with secrets stripped and cwd pinned."""
    workdir = Path(workdir or tempfile.mkdtemp(prefix="centbot-sandbox-"))
    workdir.mkdir(parents=True, exist_ok=True)
    if script_path is None:
        script_path = workdir / "_run.py"
        script_path.write_text(code or "print('ok')", encoding="utf-8")

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PRIVATE"))
    }
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(filter(None, [str(workdir), env.get("PYTHONPATH", "")])),
            "TMPDIR": str(workdir),
            "CENTBOT_SANDBOX": "1",
        }
    )
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
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
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "workdir": str(workdir)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "workdir": str(workdir)}


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
    """Health check used by the engine and tests."""
    result = run_python_isolated(code="print('centbot-sandbox-ok')", timeout=10)
    return bool(result.get("ok")) and "centbot-sandbox-ok" in (result.get("stdout") or "")
