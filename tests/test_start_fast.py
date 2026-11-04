"""START must not hang on missing AVDs / must default to skip emulators."""

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
    out = start_emulators(count=4)
    assert out.get("skipped") is True
    assert out.get("reason") == "no_centbot_avds"
    assert slept == []  # no boot wait


def test_start_cli_defaults_to_skip_emulators(monkeypatch):
    import sys

    captured = {}

    def fake_full_start(*, skip_emulators=False):
        captured["skip"] = skip_emulators
        return {"ok": True, "engine": {"ok": True}}

    monkeypatch.setattr(start_mod, "full_start", fake_full_start)
    monkeypatch.setattr(start_mod, "setup_incomplete", lambda: False)
    monkeypatch.setattr(sys, "argv", ["centbot.windows.start"])
    assert start_mod.main() == 0
    assert captured["skip"] is True


def test_start_bat_passes_skip_emulators():
    text = Path("START.bat").read_text(encoding="utf-8", errors="ignore")
    assert "--skip-emulators" in text
