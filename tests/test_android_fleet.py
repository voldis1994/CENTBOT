"""Android SDK / AVD / ADB / worker binding tests (no real emulator required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from centbot.android import adb as adb_mod
from centbot.android.emulator import EmulatorManager
from centbot.windows.avd import AVD_NAMES, ensure_centbot_avds
from centbot.windows.launcher import start_emulators
from centbot.workers.distributor import SmartWorkDistributor


def test_devices_detailed_parses_adb_l(monkeypatch):
    monkeypatch.setattr(
        adb_mod,
        "adb",
        lambda cmd, adb_path="adb", timeout=30.0: {
            "ok": True,
            "stdout": (
                "List of devices attached\n"
                "emulator-5554 device product:sdk_gphone model:sdk_gphone device:generic transport_id:1\n"
                "emulator-5556 offline product:sdk model:sdk device:generic\n"
            ),
        },
    )
    rows = adb_mod.devices_detailed()
    assert len(rows) == 2
    assert rows[0]["serial"] == "emulator-5554"
    assert rows[0]["ready"] is True
    assert rows[1]["ready"] is False


def test_wait_boot_completed(monkeypatch):
    calls = {"n": 0}

    def fake_check_output(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return "0\n"
        return "1\n"

    monkeypatch.setattr(adb_mod.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(adb_mod.time, "sleep", lambda *_: None)
    out = adb_mod.wait_boot_completed("adb", serial="emulator-5554", timeout_s=5, poll_s=0)
    assert out["ok"] is True


def test_ensure_avds_skips_existing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "centbot.windows.avd.full_hw_report",
        lambda: {
            "recommended_emulators": 4,
            "blockers": [],
            "ram": {"total_gb": 32},
            "cpu": {"physical_cores": 8},
            "virtualization": {"ok": True},
        },
    )
    monkeypatch.setattr("centbot.windows.avd.shutil.which", lambda x: "/usr/bin/" + str(x))
    created = []

    def fake_create(avdmanager, name, package, device):
        created.append(name)
        return {"ok": True, "device": device}

    monkeypatch.setattr("centbot.windows.avd._create_avd", fake_create)
    monkeypatch.setattr("centbot.windows.avd._write_avd_config_tweaks", lambda *a, **k: None)
    monkeypatch.setattr("centbot.windows.avd._run", lambda *a, **k: {"ok": True})

    states = {"n": 0}

    def list_side(*_a, **_k):
        states["n"] += 1
        if states["n"] == 1:
            return ["CENTBOT_ANDROID_01", "CENTBOT_ANDROID_02"]
        return list(AVD_NAMES)

    monkeypatch.setattr("centbot.windows.avd.list_avds", list_side)
    result = ensure_centbot_avds(count=4, sdkmanager="sdkmanager", avdmanager="avdmanager")
    assert "CENTBOT_ANDROID_01" in result["skipped_existing"]
    assert "CENTBOT_ANDROID_02" in result["skipped_existing"]
    assert "CENTBOT_ANDROID_03" in created
    assert "CENTBOT_ANDROID_04" in created


def test_emulator_stop_all_only_centbot(monkeypatch):
    mgr = EmulatorManager(enabled=True, avds=list(AVD_NAMES))
    killed = []

    monkeypatch.setattr(
        "centbot.android.emulator.devices_detailed",
        lambda *_a, **_k: [
            {"serial": "emulator-5554", "ready": True, "is_emulator": True},
            {"serial": "emulator-5556", "ready": True, "is_emulator": True},
        ],
    )

    def fake_avd(adb, serial):
        return "CENTBOT_ANDROID_01" if serial.endswith("5554") else "Pixel_Foreign"

    monkeypatch.setattr("centbot.android.emulator.emulator_avd_name", fake_avd)

    def fake_run(cmd, **kwargs):
        killed.append(cmd)
        return MagicMock()

    monkeypatch.setattr("centbot.android.emulator.subprocess.run", fake_run)
    mgr.stop_all()
    assert any("emulator-5554" in str(c) for c in killed)
    assert not any("emulator-5556" in str(c) for c in killed)


def test_start_emulators_waits_boot(monkeypatch):
    import centbot.android.adb as adb_mod2

    monkeypatch.setattr("centbot.windows.launcher.list_avds", lambda *_: ["CENTBOT_ANDROID_01"])
    monkeypatch.setattr("centbot.windows.launcher.plan_emulator_count", lambda: {"recommended": 1})
    monkeypatch.setattr(adb_mod2, "ensure_server", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(adb_mod2, "devices", lambda *_a, **_k: ["emulator-5554"])
    monkeypatch.setattr(
        adb_mod2,
        "devices_detailed",
        lambda *_a, **_k: [{"serial": "emulator-5554", "ready": True, "is_emulator": True}],
    )
    monkeypatch.setattr(adb_mod2, "emulator_avd_name", lambda *_a, **_k: "CENTBOT_ANDROID_01")

    class Proc:
        pid = 4242

    monkeypatch.setattr("centbot.windows.launcher.subprocess.Popen", lambda *a, **k: Proc())
    monkeypatch.setattr("centbot.windows.launcher.time.sleep", lambda *_: None)
    monkeypatch.setattr("centbot.windows.launcher.wait_for_boot", lambda *a, **k: {"ok": True, "serial": "emulator-5554"})

    out = start_emulators(count=1, wait_boot=True, boot_timeout_s=5)
    assert out.get("ok") is True
    assert out["started"][0]["ok"] is True
    assert any(b.get("ok") for b in out.get("boots") or [])


def test_distributor_binds_avd_slots():
    dist = SmartWorkDistributor(android_slots=4)
    dist.bind_android_slots(
        [
            {"worker": "android_1", "avd": "CENTBOT_ANDROID_01", "serial": "emulator-5554"},
            {"worker": "android_2", "avd": "CENTBOT_ANDROID_02", "serial": "emulator-5556"},
        ]
    )
    assert dist.workers["android_1"].serial == "emulator-5554"
    assert dist.workers["android_1"].avd == "CENTBOT_ANDROID_01"
    assert dist.workers["android_2"].avd == "CENTBOT_ANDROID_02"


def test_android_executor_create_path(tmp_path: Path, monkeypatch):
    from centbot.executors.android_exec import AndroidExecutor

    monkeypatch.setattr(
        "centbot.executors.android_exec.EmulatorManager.status",
        lambda self: {
            "emulator_installed": True,
            "running_devices": ["emulator-5554"],
            "serial_by_avd": {"CENTBOT_ANDROID_01": "emulator-5554"},
        },
    )
    monkeypatch.setattr("centbot.executors.android_exec.devices", lambda *_: ["emulator-5554"])
    monkeypatch.setattr("centbot.executors.android_exec.wait_boot_completed", lambda *a, **k: {"ok": True})

    class FakeTester:
        def __init__(self, *a, **k):
            pass

        def install_apk(self, *_a, **_k):
            return {"ok": True}

        def smoke_test(self, evidence):
            p = Path(evidence) / "android_smoke.png"
            p.write_bytes(b"png")
            return {"ok": True, "screenshot": {"ok": True}}

    monkeypatch.setattr("centbot.executors.android_exec.AppTestingModule", FakeTester)
    ex = AndroidExecutor(enabled=True)
    result = ex.execute({"id": "t1", "android_avd": "CENTBOT_ANDROID_01", "title": "apk smoke"}, tmp_path)
    assert result.ok is True
    assert result.artifacts
