"""Userspace restrictions applied inside the sandbox child process.

Blocks network modules and confines filesystem access to the workdir
(plus read-only access to the Python standard library / interpreter tree).
"""

from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path

# Import before installing the import guard.
try:
    import resource as _resource
except Exception:  # pragma: no cover
    _resource = None  # type: ignore[assignment]


def _python_read_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in (
        getattr(sys, "base_prefix", None),
        getattr(sys, "prefix", None),
        getattr(sys, "exec_prefix", None),
        getattr(sys, "base_exec_prefix", None),
    ):
        if candidate:
            try:
                roots.append(Path(candidate).resolve())
            except Exception:
                continue
    # Also allow the interpreter binary's directory tree
    try:
        roots.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    # Deduplicate
    uniq: list[Path] = []
    for r in roots:
        if r not in uniq:
            uniq.append(r)
    return uniq


def install(workdir: str) -> None:
    root = Path(workdir).resolve()
    os.environ["CENTBOT_SANDBOX"] = "1"
    os.environ["CENTBOT_SANDBOX_ROOT"] = str(root)
    py_roots = _python_read_roots()

    if _resource is not None:
        try:
            soft, hard = _resource.getrlimit(_resource.RLIMIT_AS)
            limit = 512 * 1024 * 1024
            if hard == _resource.RLIM_INFINITY or hard >= limit:
                _resource.setrlimit(
                    _resource.RLIMIT_AS,
                    (min(limit, hard if hard != _resource.RLIM_INFINITY else limit), hard),
                )
            _resource.setrlimit(_resource.RLIMIT_CPU, (60, 60))
        except Exception:
            pass

    _blocked = {
        "socket",
        "ssl",
        "http",
        "http.client",
        "urllib",
        "urllib.request",
        "urllib3",
        "requests",
        "aiohttp",
        "ftplib",
        "smtplib",
        "subprocess",
        "multiprocessing",
        "ctypes",
        "cffi",
        "pty",
        "fcntl",
    }
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A001
        base = name.split(".")[0]
        if name in _blocked or base in _blocked:
            raise ImportError(f"sandbox blocked import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded_import  # type: ignore[assignment]

    real_open = builtins.open

    def _under(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False

    def _allowed(path: str | os.PathLike[str], *, writing: bool) -> bool:
        try:
            resolved = Path(path).resolve()
        except Exception:
            return False
        if _under(resolved, root):
            return True
        if writing:
            return False
        # Read-only: Python interpreter / stdlib trees so imports still work
        return any(_under(resolved, py) for py in py_roots)

    def guarded_open(file, mode="r", *args, **kwargs):
        mode_s = str(mode) if mode is not None else "r"
        writing = any(c in mode_s for c in "wax+")
        if not _allowed(file, writing=writing):
            raise PermissionError(f"sandbox filesystem deny: {file}")
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open  # type: ignore[assignment]
