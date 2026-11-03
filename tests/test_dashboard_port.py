"""Dashboard port bind / bump / wait helpers."""

from __future__ import annotations

import socket
from pathlib import Path

from centbot.dashboard.app import create_dashboard, read_dashboard_state, start_dashboard_thread, write_dashboard_state
from centbot.dashboard.portutil import can_bind, pick_port, port_open, wait_for_port


def test_write_and_read_dashboard_state(tmp_path: Path, monkeypatch):
    import centbot.dashboard.app as dash

    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    monkeypatch.setattr(dash, "_dashboard_state_path", lambda: tmp_path / "data" / "runtime" / "dashboard.json")
    path = write_dashboard_state("127.0.0.1", 8799, extra={"bumped": True})
    assert path.exists()
    state = read_dashboard_state()
    assert state["port"] == 8799
    assert state["bumped"] is True
    assert "8799" in state["url"]


def test_start_dashboard_uses_free_port_when_preferred_busy(tmp_path: Path, monkeypatch):
    import centbot.dashboard.app as dash

    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    monkeypatch.setattr(dash, "_dashboard_state_path", lambda: tmp_path / "data" / "runtime" / "dashboard.json")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    busy = sock.getsockname()[1]
    try:
        app = create_dashboard(lambda: {"ok": True}, lambda: None)
        start_dashboard_thread(app, "127.0.0.1", busy)
        state = read_dashboard_state()
        assert int(state["port"]) != busy
        assert wait_for_port("127.0.0.1", int(state["port"]), timeout_s=8)
        assert port_open("127.0.0.1", int(state["port"]))
    finally:
        sock.close()


def test_can_bind_false_when_held():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        # Another bind to same port should fail while held (platform-dependent with REUSEADDR)
        choice = pick_port("127.0.0.1", port, attempts=3)
        assert choice["ok"] is True
        assert isinstance(choice["port"], int)
    finally:
        sock.close()
