"""Docker sandbox helper unit tests (no daemon required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from centbot.windows.docker_sandbox import docker_info, write_docker_env


def test_docker_info_missing(monkeypatch):
    monkeypatch.setattr("centbot.windows.docker_sandbox.shutil.which", lambda *_a, **_k: None)
    info = docker_info()
    assert info["ok"] is False
    assert info["error"] == "docker_not_on_path"


def test_write_docker_env(tmp_path: Path):
    path = write_docker_env({"ok": True, "require_container": "1"}, root=tmp_path)
    assert path and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "CENTBOT_REQUIRE_CONTAINER=1" in text
    assert "CENTBOT_SANDBOX_BACKEND=docker" in text


def test_windows_volume_path_uses_forward_slashes():
    from centbot.sandbox import container as c

    src = Path(c.__file__).read_text(encoding="utf-8")
    assert "host_work" in src and "replace" in src and "win" in src
