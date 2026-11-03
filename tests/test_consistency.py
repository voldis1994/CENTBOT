"""Config true/false consistency — live must not be soft-blocked into fake idle."""

from __future__ import annotations

from pathlib import Path

from centbot.core.config import Config
from centbot.core.consistency import audit_config
from centbot.windows.wizard import apply_answers, build_local_yaml


def test_default_config_is_live_oriented():
    cfg = Config()
    report = audit_config(cfg)
    assert report["flags"]["live"] is True
    assert report["flags"]["auto_accept"] is True
    assert report["flags"]["android.enabled"] is True
    assert report["flags"]["simulate_rewards_in_dry_run"] is False
    assert report["ok"] is True
    # Wallet empty → not fully ready, but start must still be allowed (warning only)
    assert report["ready_for_live"] is False
    assert any("wallet" in w for w in report["warnings"])


def test_live_without_wallet_is_warning_not_hard_block():
    cfg = Config(
        overrides={
            "system": {"mode": "live", "max_parallel_tasks": 6},
            "analysis": {"auto_accept": True},
            "finance": {"crypto_wallet_public": "", "simulate_rewards_in_dry_run": False},
            "android": {"enabled": True, "max_emulators": 4},
        }
    )
    report = audit_config(cfg)
    assert report["ok"] is True
    assert report["ready_for_live"] is False
    assert report["blockers"] == [] or "simulate" not in str(report["blockers"])


def test_live_ready_when_wallet_set():
    cfg = Config(
        overrides={
            "system": {"mode": "live", "max_parallel_tasks": 6},
            "analysis": {"auto_accept": True},
            "finance": {
                "crypto_wallet_public": "0x" + "ab" * 20,
                "simulate_rewards_in_dry_run": False,
            },
            "android": {"enabled": True, "max_emulators": 4},
        }
    )
    report = audit_config(cfg)
    assert report["ready_for_live"] is True


def test_wizard_rejects_incomplete_without_writing(tmp_path: Path):
    bad = apply_answers({"mode": "live", "email": "x"}, root=tmp_path, allow_partial=False)
    assert bad["ok"] is False
    assert bad.get("wrote") is False
    assert not (tmp_path / "config" / "local.yaml").exists()


def test_wizard_live_defaults_auto_accept_and_android():
    data = build_local_yaml(
        {
            "mode": "live",
            "full_name": "A B",
            "iban": "LV97HABA0012345678910",
            "crypto_wallet": "0x" + "cd" * 20,
        }
    )
    assert data["analysis"]["auto_accept"] is True
    assert data["android"]["enabled"] is True
    assert data["system"]["mode"] == "live"


def test_wizard_writes_only_when_valid(tmp_path: Path):
    ok = apply_answers(
        {
            "full_name": "Jānis Bērziņš",
            "country": "Latvia",
            "email": "janis@example.com",
            "bank_holder": "Jānis Bērziņš",
            "iban": "LV97HABA0012345678910",
            "bank_currency": "EUR",
            "crypto_wallet": "0x" + "ab" * 20,
            "mode": "live",
            "min_profit": "0.5",
        },
        root=tmp_path,
        allow_partial=False,
    )
    assert ok["ok"] is True and ok.get("wrote") is True
    assert (tmp_path / "config" / "local.yaml").exists()


def test_parallel_starvation_warning():
    cfg = Config(
        overrides={
            "system": {"mode": "live", "max_parallel_tasks": 2},
            "android": {"enabled": True, "max_emulators": 4},
            "finance": {"crypto_wallet_public": "0x" + "11" * 20},
        }
    )
    report = audit_config(cfg)
    assert any("starve" in w for w in report["warnings"])


def test_engine_live_does_not_hard_block_schedule(tmp_path: Path):
    from unittest.mock import MagicMock

    from centbot.core.engine import CentBotEngine

    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()
    cfg = Config(
        overrides={
            "system": {
                "mode": "live",
                "max_parallel_tasks": 2,
                "pid_file": str(tmp_path / "data" / "pid"),
                "emergency_stop_file": str(tmp_path / "data" / "STOP"),
            },
            "database": {"path": str(tmp_path / "data" / "c.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"enabled": False, "directory": str(tmp_path / "backups")},
            "security": {"credentials_file": str(tmp_path / "data" / "cred.enc")},
            "dashboard": {"enabled": False},
            "analysis": {"auto_accept": True},
            "finance": {"crypto_wallet_public": "0x" + "11" * 20, "reconcile_payments": False},
            "platforms": {
                "jobbi": {"enabled": False},
                "basedagents": {"enabled": False},
                "taskmarket": {"enabled": False},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": False},
            },
            "android": {"enabled": False},
            "browser": {"enabled": False},
            "discovery": {"auto_discover_platforms": False},
        }
    )
    engine = CentBotEngine(cfg)
    assert engine.config.is_live()
    assert engine.acceptor.dry_run is False
    assert engine.submitter.dry_run is False

    class Fake:
        def accept_task(self, task):
            return {"ok": False, "error": "platform_auth_required"}

    engine.platforms = {"fake": Fake()}
    engine.acceptor.platforms = engine.platforms
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, "
        "reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("t1", "fake", "e1", "job", "x", "text", "eligible", 5.0, "USD", 80),
    )
    launched = engine.schedule_eligible()
    assert launched == 0  # accept failed honestly
    alerts = engine.db.fetchall("SELECT message FROM alerts")
    assert any("Accept failed" in (a["message"] or "") for a in alerts)
    engine.shutdown()
