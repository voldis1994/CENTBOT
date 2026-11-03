"""Sandbox diagnose must soft-fail without crashing when Docker image missing."""

from __future__ import annotations

from unittest.mock import patch

from centbot.sandbox.isolated import sandbox_diagnose


def test_diagnose_fast_fail_when_image_missing():
    with (
        patch("centbot.sandbox.container.available_backends", return_value={"docker": True, "podman": False, "unshare_container": False, "windows_vm": False}),
        patch("centbot.sandbox.container.select_backend", return_value="docker"),
        patch("centbot.windows.docker_sandbox.docker_info", return_value={"ok": True, "exe": "docker"}),
        patch("centbot.windows.docker_sandbox.image_present", return_value=False),
    ):
        diag = sandbox_diagnose()
    assert diag["ok"] is False
    assert diag["error"] == "sandbox_image_missing"
    assert "ENSURE_DOCKER" in (diag.get("hint_lv") or "")
