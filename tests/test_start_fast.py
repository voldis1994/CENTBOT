"""START must not hang on missing AVDs; --with-emulators wins over --skip-emulators."""

from __future__ import annotations

from pathlib import Path

from centbot.windows.launcher import start_emulators
from centbot.windows import start as start_mod


def test_start_emulators_fast_when_no_avds(monkeypatch):
    monkeypatch.setattr("centbot.windows.launcher.list_avds", lambda *_a, **_k: [])
    monkeypatch.setattr("centbot.windows.launcher.plan_emulator_count", lambda: {"recommended": 4})
    slept = []

    def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("centbot.windows.launcher.time.sleep", fake_sleep)
    import centbot.android.adb as adb_mod

    monkeypatch.setattr(adb_mod, "ensure_server", lambda *_a, **_k: {"ok": True})
    out = start_emulators(count=4, wait_boot=False)
    assert out.get("skipped") is True
    assert out.get("reason") == "no_centbot_avds"
    assert slept == []  # no boot wait when no AVDs


def test_start_cli_skip_flag(monkeypatch):
    import sys

    captured = {}

    def fake_full_start(*, skip_emulators=False):
        captured["skip"] = skip_emulators
        return {"ok": True, "engine": {"ok": True}}

    monkeypatch.setattr(start_mod, "full_start", fake_full_start)
    monkeypatch.setattr(start_mod, "setup_incomplete", lambda: False)
    monkeypatch.delenv("CENTBOT_START_EMULATORS", raising=False)
    monkeypatch.setattr(sys, "argv", ["centbot.windows.start", "--skip-emulators"])
    assert start_mod.main() == 0
    assert captured["skip"] is True


def test_start_bat_supports_emulator_env_controls():
    text = Path("START.bat").read_text(encoding="utf-8", errors="ignore")
    assert "CENTBOT_START_EMULATORS" in text
    assert "--with-emulators" in text
    # Default is no longer a hard-coded unconditional --skip-emulators launch
    assert 'centbot.windows.start --skip-emulators' not in text.replace("%START_ARGS%", "X")
