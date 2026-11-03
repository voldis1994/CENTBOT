"""Config true/false consistency — system must not disagree with itself."""

from __future__ import annotations

from pathlib import Path

from centbot.core.config import Config
from centbot.core.consistency import audit_config
from centbot.windows.wizard import build_local_yaml


def test_default_config_dry_run_is_internally_ok():
    cfg = Config()
    report = audit_config(cfg)
    assert report["flags"]["live"] is False
    assert report["flags"]["auto_accept"] is False
    assert report["flags"]["simulate_rewards_in_dry_run"] is False
    assert report["ok"] is True  # dry_run defaults are coherent
    assert report["ready_for_live"] is False
    # Warning: 4 emulators configured while android.enabled false
    assert any("android.enabled_is_false" in w for w in report["warnings"])


def test_live_without_auto_accept_blocked():
    cfg = Config(
        overrides={
            "system": {"mode": "live", "max_parallel_tasks": 6},
            "analysis": {"auto_accept": False},
            "finance": {"crypto_wallet_public": "0x" + "11" * 20, "simulate_rewards_in_dry_run": False},
            "android": {"enabled": True, "max_emulators": 4},
        }
    )
    report = audit_config(cfg)
    assert report["ready_for_live"] is False
    assert "live_requires_analysis.auto_accept_true" in report["blockers"]


def test_live_ready_when_flags_align():
    cfg = Config(
        overrides={
            "system": {"mode": "live", "max_parallel_tasks": 6},
            "analysis": {"auto_accept": True},
            "finance": {
                "crypto_wallet_public": "0x" + "ab" * 20,
                "simulate_rewards_in_dry_run": False,
                "reconcile_payments": True,
                "verify_on_chain": True,
            },
            "android": {"enabled": True, "max_emulators": 4},
        }
    )
    report = audit_config(cfg)
    assert report["blockers"] == [] or not any("live_requires" in b for b in report["blockers"])
    assert report["ready_for_live"] is True
    assert report["flags"]["android.enabled"] is True
    assert report["flags"]["system.max_parallel_tasks"] >= report["flags"]["android.max_emulators"]


def test_wizard_live_defaults_auto_accept_true():
    data = build_local_yaml(
        {
            "mode": "live",
            "full_name": "A",
            "iban": "LV97HABA0012345678910",
            "crypto_wallet": "0x" + "cd" * 20,
        }
    )
    assert data["analysis"]["auto_accept"] is True
    assert data["android"]["enabled"] is True
    assert data["system"]["max_parallel_tasks"] == 6
    assert data["finance"]["simulate_rewards_in_dry_run"] is False


def test_wizard_dry_run_keeps_auto_accept_false():
    data = build_local_yaml({"mode": "dry_run", "auto_accept": True})
    # Even if answered true, dry_run must not enable live claims
    assert data["analysis"]["auto_accept"] is False


def test_parallel_starvation_warning():
    cfg = Config(
        overrides={
            "system": {"mode": "dry_run", "max_parallel_tasks": 2},
            "android": {"enabled": True, "max_emulators": 4},
        }
    )
    report = audit_config(cfg)
    assert any("max_parallel_tasks" in w and "starve" in w for w in report["warnings"])


def test_engine_status_includes_consistency(tmp_path: Path):
    from centbot.core.engine import CentBotEngine

    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()
    cfg = Config(
        overrides={
            "system": {
                "mode": "dry_run",
                "max_parallel_tasks": 6,
                "pid_file": str(tmp_path / "data" / "pid"),
                "emergency_stop_file": str(tmp_path / "data" / "STOP"),
            },
            "database": {"path": str(tmp_path / "data" / "c.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"enabled": False, "directory": str(tmp_path / "backups")},
            "security": {"credentials_file": str(tmp_path / "data" / "cred.enc")},
            "dashboard": {"enabled": False},
            "platforms": {
                "jobbi": {"enabled": False},
                "basedagents": {"enabled": False},
                "taskmarket": {"enabled": False},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": False},
            },
            "android": {"enabled": True, "max_emulators": 4},
            "browser": {"enabled": False},
        }
    )
    engine = CentBotEngine(cfg)
    st = engine.status()
    assert "consistency" in st
    assert st["android"]["enabled"] is True
    assert st["settings"]["android_enabled"] is True
    assert engine.distributor.workers["android_1"].capacity == 1
    engine.shutdown()


def test_android_disabled_zeros_distributor_slots(tmp_path: Path):
    from centbot.core.engine import CentBotEngine

    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()
    cfg = Config(
        overrides={
            "system": {
                "mode": "dry_run",
                "pid_file": str(tmp_path / "data" / "pid"),
                "emergency_stop_file": str(tmp_path / "data" / "STOP"),
            },
            "database": {"path": str(tmp_path / "data" / "c.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"enabled": False, "directory": str(tmp_path / "backups")},
            "security": {"credentials_file": str(tmp_path / "data" / "cred.enc")},
            "dashboard": {"enabled": False},
            "platforms": {
                "jobbi": {"enabled": False},
                "basedagents": {"enabled": False},
                "taskmarket": {"enabled": False},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": False},
            },
            "android": {"enabled": False, "max_emulators": 4},
            "browser": {"enabled": False},
        }
    )
    engine = CentBotEngine(cfg)
    assert engine.distributor.workers["android_1"].capacity == 0
    engine.shutdown()
