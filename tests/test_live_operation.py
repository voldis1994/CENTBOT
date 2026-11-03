"""REAL LIVE OPERATION gates: no fake success, live vs dry_run isolation, ops evidence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from centbot.core.config import Config
from centbot.core.database import Database
from centbot.core.engine import CentBotEngine
from centbot.core.logger import ActionJournal
from centbot.finance.ledger import FinanceLedger
from centbot.platforms.response import interpret_platform_result
from centbot.quality.ops_report import build_operations_report, write_operations_report


def _mk_engine(tmp_path: Path, *, mode: str = "dry_run", auto_accept: bool = False, wallet: str = "") -> CentBotEngine:
    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    cfg = Config(
        overrides={
            "system": {
                "mode": mode,
                "pid_file": str(tmp_path / "data" / "centbot.pid"),
                "emergency_stop_file": str(tmp_path / "data" / "EMERGENCY_STOP"),
                "max_parallel_tasks": 1,
            },
            "database": {"path": str(tmp_path / "data" / "centbot.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"enabled": False, "directory": str(tmp_path / "backups")},
            "security": {"credentials_file": str(tmp_path / "data" / "credentials.enc")},
            "dashboard": {"enabled": False},
            "analysis": {"auto_accept": auto_accept, "min_expected_profit": 0.01},
            "platforms": {"bountybook": {"enabled": False}},
            "finance": {
                "simulate_rewards_in_dry_run": False,
                "reconcile_payments": True,
                "crypto_wallet_public": wallet,
            },
            "browser": {"enabled": False},
            "android": {"enabled": False},
        }
    )
    return CentBotEngine(cfg)


def test_interpret_platform_result_never_defaults_success():
    assert interpret_platform_result(None)["ok"] is False
    assert interpret_platform_result({})["ok"] is False
    assert interpret_platform_result({"error": "nope"})["ok"] is False
    assert interpret_platform_result({"ok": False})["ok"] is False
    assert interpret_platform_result({"ok": True})["ok"] is True
    assert interpret_platform_result({"status": "claimed"})["ok"] is True
    assert interpret_platform_result({"claim_id": "c1"})["ok"] is True
    assert interpret_platform_result({"message": "maybe"})["ok"] is False


def test_live_readiness_blockers_when_not_configured(tmp_path: Path):
    engine = _mk_engine(tmp_path, mode="dry_run")
    r = engine.live_readiness()
    assert r["live"] is False
    assert r["ready"] is False
    assert "system.mode_not_live" in r["blockers"]
    engine.shutdown()

    live = _mk_engine(tmp_path / "live", mode="live", auto_accept=False, wallet="")
    r2 = live.live_readiness()
    assert r2["live"] is True
    assert r2["ready"] is False
    assert "analysis.auto_accept_disabled" in r2["blockers"]
    assert "finance.crypto_wallet_public_missing" in r2["blockers"]
    live.shutdown()


def test_intentional_live_not_overridden_by_uncontrolled_trial(tmp_path: Path):
    engine = _mk_engine(tmp_path, mode="live", auto_accept=True, wallet="0x" + "11" * 20)
    assert engine.config.is_live()
    # Default controlled=False must respect intentional live (no silent force_dry_run)
    report = engine.run_live_trial(execute_local=False, controlled=False)
    assert report["mode"] == "live"
    assert report["controlled"] is False
    assert engine.config.is_live()
    assert engine.acceptor.dry_run is False
    assert engine.submitter.dry_run is False
    # Live trial without controlled does discovery only (no practice auto-claim)
    assert report["executed"] == []
    engine.shutdown()


def test_controlled_explicitly_forces_dry_run_over_live(tmp_path: Path):
    engine = _mk_engine(tmp_path, mode="live", auto_accept=True, wallet="0x" + "22" * 20)
    report = engine.run_live_trial(execute_local=False, controlled=True)
    assert report["controlled"] is True
    assert report["mode"] == "dry_run"
    assert report["claims_allowed"] is False
    assert report["verification"]["external_accept_blocked"] is True
    assert report["verification"]["external_payment_booking_blocked"] is True
    assert engine.config.is_dry_run()
    engine.shutdown()


def test_dry_run_statuses_excluded_from_verified_ops_success(tmp_path: Path):
    engine = _mk_engine(tmp_path, mode="dry_run")
    db = engine.db
    db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, "
        "reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("d1", "jobbi", "ext-d1", "dry practice", "x", "text", "dry_run_accepted", 5.0, "USD", 50),
    )
    db.execute(
        "INSERT INTO submissions(task_id, platform, status, submitted_at, response_json) VALUES(?,?,?,?,?)",
        ("d1", "jobbi", "dry_run_submitted", "2020-01-01T00:00:00Z", "{}"),
    )
    report = engine.operations_report()
    assert report["live"] is False
    assert report["accepted"]["live_rows"] == 0
    assert report["submissions"]["platform_submissions"] == 0
    assert report["verified_success"]["has_real_submission"] is False
    assert report["verified_success"]["has_verified_income"] is False
    assert report["verified_success"]["profit_positive"] is False
    assert report["finances"]["total_profit"] in (0, 0.0, None) or float(report["finances"]["total_profit"] or 0) == 0
    out = write_operations_report(tmp_path / "ops.json", report)
    assert out.exists()
    engine.shutdown()


def test_ops_report_counts_only_ledger_backed_income(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    journal = ActionJournal(tmp_path)
    ledger = FinanceLedger(db, journal, wallet_public="0xabc")
    assert ledger.record_bank_reward(amount=12.5, currency="EUR", platform="jobbi", tx_ref="bank-tx-1")
    assert ledger.record_crypto_reward(amount=3.0, currency="USDC", platform="basedagents", tx_ref="0x" + "cd" * 32)
    report = build_operations_report(db=db, ledger=ledger, journal_dir=tmp_path, mode="live", live=True)
    assert report["payments"]["bank_count"] == 1
    assert report["payments"]["crypto_count"] == 1
    assert report["verified_success"]["has_verified_income"] is True
    assert report["verified_success"]["profit_positive"] is True
    # Profit is FX-converted to base currency — only require positive verified sum
    assert float(report["finances"]["total_profit"]) > 0


def test_cli_mode_live_alone_does_not_force_dry_run(tmp_path: Path, monkeypatch, capsys):
    from centbot import __main__ as cli

    calls: dict = {}

    class FakeEngine:
        def __init__(self, config):
            calls["mode"] = config.get("system.mode")
            self.config = config

        def live_readiness(self):
            return {"live": True, "ready": False, "blockers": ["finance.crypto_wallet_public_missing"]}

        def shutdown(self):
            return None

        def cycle_once(self):
            calls["cycled"] = True
            return {"ok": True}

        def run_forever(self):
            calls["forever"] = True

    monkeypatch.setattr(cli, "CentBotEngine", FakeEngine)
    # Live with partial readiness warns then continues — never hard-stops into fake idle
    rc = cli.main(["--mode", "live", "--once"])
    assert calls["mode"] == "live"
    assert calls.get("cycled") is True
    assert rc == 0
    out = capsys.readouterr().out
    assert "live_partial_readiness" in out


def test_schedule_live_attempts_accept_and_surfaces_failure(tmp_path: Path):
    """Live must attempt real claims even when readiness is incomplete — so failures are visible."""
    engine = _mk_engine(tmp_path, mode="live", auto_accept=False, wallet="")
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, "
        "reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("t-live", "jobbi", "ext-1", "real gig", "do work", "text", "eligible", 10.0, "USD", 90),
    )
    accept_calls: list = []

    class FakeFail:
        name = "jobbi"
        enabled = True

        def accept_task(self, task):
            accept_calls.append(task)
            return {"ok": False, "error": "platform_auth_required"}

        def list_tasks(self):
            return []

        def health(self):
            return {"ok": True, "platform": "jobbi"}

        def check_automation_rules(self):
            return {"automation_allowed": True}

    engine.platforms = {"jobbi": FakeFail()}
    engine.acceptor.platforms = engine.platforms
    launched = engine.schedule_eligible()
    assert launched == 0
    assert len(accept_calls) == 1  # real claim attempted
    row = engine.db.fetchone("SELECT status FROM tasks WHERE id=?", ("t-live",))
    assert row["status"] == "eligible"  # never faked as accepted
    alerts = engine.db.fetchall("SELECT message FROM alerts")
    assert any("Accept failed" in (a["message"] or "") for a in alerts)
    engine.shutdown()


def test_schedule_live_accepts_when_platform_ok(tmp_path: Path):
    engine = _mk_engine(tmp_path, mode="live", auto_accept=False, wallet="0x" + "11" * 20)
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, "
        "reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("t-ok", "jobbi", "ext-2", "real gig", "do work", "text", "eligible", 10.0, "USD", 90),
    )

    class FakeOk:
        name = "jobbi"
        enabled = True

        def accept_task(self, task):
            return {"ok": True, "claim_id": "c1"}

        def list_tasks(self):
            return []

        def health(self):
            return {"ok": True, "platform": "jobbi"}

        def check_automation_rules(self):
            return {"automation_allowed": True}

    engine.platforms = {"jobbi": FakeOk()}
    engine.acceptor.platforms = engine.platforms
    launched = engine.schedule_eligible()
    assert launched == 1
    row = engine.db.fetchone("SELECT status FROM tasks WHERE id=?", ("t-ok",))
    # Accept succeeded; pool may already advance eligible→accepted→running
    assert row["status"] in {"accepted", "running", "needs_repair", "failed"}
    engine.shutdown()


def test_reconcile_blocked_in_dry_run_never_books_fake_profit(tmp_path: Path):
    engine = _mk_engine(tmp_path, mode="dry_run")
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, "
        "reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("paid-ish", "fake", "ext-p", "x", "y", "text", "submitted", 99.0, "USDC", 50),
    )

    class FakePay:
        def check_payment(self, external_id):
            return {
                "payment_status": "settled",
                "payment_tx_hash": "0x" + "ab" * 32,
                "to": "0x" + "11" * 20,
                "amount": 99,
                "currency": "USDC",
            }

    engine.platforms["fake"] = FakePay()
    updates = engine.reconcile_payments()
    assert updates == []
    assert float(engine.ledger.total_profit()) == 0.0
    engine.shutdown()
