"""Android SDK path resolution (no real Studio required)."""

from __future__ import annotations

from pathlib import Path

from centbot.windows.android_sdk import candidate_sdk_roots, resolve_sdk_tools


def test_candidate_roots_include_localappdata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    roots = candidate_sdk_roots()
    assert any(str(tmp_path) in str(r) for r in roots)


def test_resolve_finds_tools_under_sdk_tree(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    plat = tmp_path / "platform-tools"
    emu = tmp_path / "emulator"
    plat.mkdir()
    emu.mkdir()
    adb = plat / "adb"
    emulator = emu / "emulator"
    adb.write_text("")
    emulator.write_text("")
    adb.chmod(0o755)
    emulator.chmod(0o755)
    # Clear PATH so which() does not mask our tree
    monkeypatch.setenv("PATH", "")
    tools = resolve_sdk_tools()
    assert tools["ok"] is True
    assert tools["adb"] and "platform-tools" in tools["adb"]
    assert tools["emulator"] and "emulator" in tools["emulator"]


def test_bountybook_offline_message():
    from centbot.platforms.bountybook import _offline_message

    assert "platform_offline_dns" in _offline_message("Failed to resolve 'api.bountybook.ai' ([Errno 11001])")


def test_write_android_env(tmp_path: Path):
    from centbot.windows.android_sdk import write_android_env

    tools = {
        "sdk_root": str(tmp_path / "Sdk"),
        "adb": str(tmp_path / "Sdk" / "platform-tools" / "adb.exe"),
        "emulator": str(tmp_path / "Sdk" / "emulator" / "emulator.exe"),
    }
    path = write_android_env(tools, root=tmp_path)
    assert path and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "ANDROID_HOME=" in text
    assert "CENTBOT_ADB=" in text


def test_download_cmdline_skipped_when_present(tmp_path: Path):
    from centbot.windows.android_sdk import download_cmdline_tools

    latest = tmp_path / "cmdline-tools" / "latest" / "bin"
    latest.mkdir(parents=True)
    marker = latest / ("sdkmanager.bat" if __import__("sys").platform.startswith("win") else "sdkmanager")
    marker.write_text("@echo off\n", encoding="utf-8")
    result = download_cmdline_tools(tmp_path)
    assert result["ok"] is True
    assert result.get("skipped") is True


def test_ensure_avds_alias_exists():
    from centbot.windows import avd

    assert callable(avd.ensure_avds)
    assert avd.ensure_avds is not None
