"""Dashboard TCP port helpers — avoid 'address already in use' and early browser open."""

from __future__ import annotations

import socket
import time
from typing import Any


def port_open(host: str, port: int, *, timeout: float = 0.35) -> bool:
    """True when something accepts TCP connections on host:port."""
    try:
        with socket.create_connection((host if host not in {"0.0.0.0", "::"} else "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def can_bind(host: str, port: int) -> bool:
    """True if we can bind the port right now (not already taken).

    Do NOT set SO_REUSEADDR here — that can falsely report a busy LISTEN/bound
    port as free and recreate 'address already in use' when Flask starts.
    """
    family = socket.AF_INET6 if ":" in host and host.count(":") > 1 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        bind_host = host
        if host in {"0.0.0.0", ""}:
            bind_host = "0.0.0.0"
        sock.bind((bind_host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def pick_port(host: str, preferred: int, *, attempts: int = 40) -> dict[str, Any]:
    """Pick preferred port or the next free one. Never claim a busy address."""
    preferred = int(preferred or 8787)
    for offset in range(max(1, attempts)):
        port = preferred + offset
        if port > 65535:
            break
        if can_bind(host, port):
            return {
                "ok": True,
                "port": port,
                "preferred": preferred,
                "bumped": port != preferred,
                "reason": None if port == preferred else "preferred_port_in_use",
            }
    return {
        "ok": False,
        "port": None,
        "preferred": preferred,
        "bumped": False,
        "reason": "no_free_port_in_range",
    }


def wait_for_port(host: str, port: int, *, timeout_s: float = 45.0, interval_s: float = 0.4) -> bool:
    """Block until the dashboard accepts connections (or timeout)."""
    probe = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if port_open(probe, port):
            return True
        time.sleep(interval_s)
    return False
