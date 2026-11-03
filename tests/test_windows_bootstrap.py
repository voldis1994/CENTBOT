"""Windows bootstrap unit tests — runnable on Linux; NOT proof of Windows install."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from centbot.windows.avd import AVD_NAMES, plan_emulator_count
from centbot.windows.hwcheck import full_hw_report, recommended_emulator_count
from centbot.windows.install_state import SetupProgress
from centbot.windows.installer import WindowsSetup
from centbot.windows.secrets import ForbiddenSecretError, SecretStore
from centbot.windows.wizard import apply_answers, build_local_yaml, validate_field
from centbot.workers.distributor import SmartWorkDistributor
from centbot.discovery.platform_registration import assess_platform, attempt_register


def test_hw_report_has_expected_keys():
    report = full_hw_report()
    assert "cpu" in report and "ram" in report and "disk" in report
    assert "recommended_emulators" in report
    assert isinstance(report["blockers"], list)


def test_recommended_emulator_count_scales():
    assert recommended_emulator_count(4, 2) == 0
    assert recommended_emulator_count(8, 4) == 2
    assert recommended_emulator_count(16, 8) == 4


def test_setup_progress_resume(tmp_path: Path):
    prog = SetupProgress(tmp_path / "progress.json")
    assert not prog.is_done("git")
    prog.mark("git", ok=True, skipped=True, detail="present")
    prog2 = SetupProgress(tmp_path / "progress.json")
    assert prog2.is_done("git")
    assert prog2.status("git")["skipped"] is True


def test_setup_skips_existing_git_and_refuses_windows_packages_on_linux(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("centbot.windows.installer.which", lambda name: "/usr/bin/git" if name == "git" else None)
    setup = WindowsSetup(root=tmp_path, progress=SetupProgress(tmp_path / "progress.json"), assume_yes=False)
    git = setup.ensure_git()
    assert git["ok"] is True and git.get("skipped") is True
    docker = setup.ensure_docker()
    # On Linux auto docker desktop install is refused
    assert docker["ok"] is False or docker.get("skipped")


def test_setup_run_resumable_with_fake_runner(tmp_path: Path):
    calls: list[list[str]] = []

    def runner(cmd, opts=None):
        calls.append(cmd)
        return {"ok": True, "stdout": "ok", "stderr": ""}

    setup = WindowsSetup(
        root=tmp_path,
        progress=SetupProgress(tmp_path / "data" / "setup" / "progress.json"),
        runner=runner,
        assume_yes=False,
    )
    # Create a minimal requirements for pip step
    (tmp_path / "requirements.txt").write_text("pyyaml>=6\n", encoding="utf-8")
    report = setup.run(create_avds=False)
    assert "steps" in report
    assert report.get("windows") is False
    assert report.get("note")  # explains not Windows
    # Second run should skip completed marks
    report2 = setup.run(create_avds=False)
    assert setup.progress.is_done("python_venv") or setup.progress.is_done("hw_check")


def test_wizard_validation_and_forbidden_secrets(tmp_path: Path):
    assert validate_field("email", "bad") == "invalid_email"
    assert validate_field("iban", "LV12TEST")  # may be invalid length
    assert validate_field("mode", "live") is None
    bad = apply_answers(
        {
            "full_name": "A B",
            "country": "LV",
            "email": "a@b.lv",
            "bank_holder": "A B",
            "iban": "LV97HABA0012345678910",
            "crypto_wallet": "0x" + "11" * 20,
            "mode": "dry_run",
            "bank_password": "nope",
        },
        root=tmp_path,
        allow_partial=True,
    )
    assert bad["ok"] is False
    assert bad["errors"]["bank_password"] == "forbidden_secret"

    ok = apply_answers(
        {
            "full_name": "Jānis Bērziņš",
            "country": "Latvia",
            "email": "janis@example.com",
            "bank_holder": "Jānis Bērziņš",
            "iban": "LV97HABA0012345678910",
            "bank_currency": "EUR",
            "crypto_wallet": "0x" + "ab" * 20,
            "mode": "dry_run",
            "min_profit": "0.5",
            "auto_register": False,
        },
        root=tmp_path,
        allow_partial=False,
    )
    assert ok["ok"] is True
    local = yaml.safe_load((tmp_path / "config" / "local.yaml").read_text(encoding="utf-8"))
    assert local["android"]["max_emulators"] == 4
    assert local["android"]["avds"][0] == "CENTBOT_ANDROID_01"
    assert local["finance"]["simulate_rewards_in_dry_run"] is False


def test_secret_store_refuses_seed(tmp_path: Path):
    store = SecretStore(tmp_path)
    store.set("api_token", "abc")
    assert store.get("api_token") == "abc"
    with pytest.raises(ForbiddenSecretError):
        store.set("seed_phrase", "alpha beta gamma")


def test_avd_plan_names():
    assert len(AVD_NAMES) == 4
    plan = plan_emulator_count()
    assert "recommended" in plan
    assert plan["names"] == AVD_NAMES[: plan["recommended"]]


def test_smart_distributor_no_duplicates_and_lanes():
    dist = SmartWorkDistributor(max_pc=2, android_slots=4)
    t1 = {"id": "t1", "category": "programming", "priority": 50}
    a1 = dist.assign(t1)
    assert a1["ok"] and a1["worker"] == "pc"
    a_dup = dist.assign(t1)
    assert a_dup["ok"] is False and a_dup["error"] == "duplicate_task"
    dist.release("t1")
    t2 = {"id": "t2", "category": "android", "priority": 90}
    a2 = dist.assign(t2)
    assert a2["ok"] and a2["worker"] in {"android_4", "android_2", "android_3", "android_1"}


def test_platform_registration_blocked_without_permission(tmp_path: Path):
    from centbot.core.config import Config

    cfg = Config(
        overrides={
            "discovery": {"auto_register_allowed": False},
            "platforms": {
                "jobbi": {"enabled": False},
                "basedagents": {"enabled": False},
                "taskmarket": {"enabled": False},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": False},
            },
        }
    )
    out = attempt_register("jobbi", config=cfg, registry_path=tmp_path / "accounts.json")
    assert out["ok"] is False
    assert out["error"] == "auto_register_disabled"

    assessment = assess_platform("x", {"ok": True, "automation": {"automation_allowed": False, "requires_human_review": True}})
    assert assessment["registerable"] is False


def test_bat_files_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "SETUP.bat").exists()
    assert (root / "START.bat").exists()
    assert (root / "STOP.bat").exists()
    setup = (root / "SETUP.bat").read_text(encoding="utf-8", errors="ignore")
    assert "centbot.windows.setup" in setup
    start = (root / "START.bat").read_text(encoding="utf-8", errors="ignore")
    assert "SETUP.bat" in start
    stop = (root / "STOP.bat").read_text(encoding="utf-8", errors="ignore")
    assert "centbot.windows.stop" in stop


def test_build_local_yaml_defaults():
    data = build_local_yaml({"mode": "live", "auto_accept": True, "iban": "LV00", "crypto_wallet": "0x1"})
    assert data["system"]["mode"] == "live"
    assert data["android"]["max_emulators"] == 4
