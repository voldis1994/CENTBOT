"""CENTBOT module interaction and dry-run tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from centbot.analysis.pipeline import AnalysisPipeline, categorize, expected_profit
from centbot.core.config import Config
from centbot.core.database import Database
from centbot.core.engine import CentBotEngine
from centbot.core.logger import ActionJournal
from centbot.core.priority import score_priority
from centbot.discovery.dedup import DuplicateFilter
from centbot.executors.router import TaskExecutorRouter
from centbot.finance.currency import to_base
from centbot.finance.ledger import FinanceLedger
from centbot.platforms.registry import build_platforms, verify_integrations
from centbot.security.credentials import CredentialStore
from centbot.security.rate_limit import RateLimiter


@pytest.fixture()
def tmp_engine(tmp_path: Path) -> CentBotEngine:
    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()
    cfg = Config(
        overrides={
            "system": {
                "mode": "dry_run",
                "pid_file": str(tmp_path / "data" / "centbot.pid"),
                "emergency_stop_file": str(tmp_path / "data" / "EMERGENCY_STOP"),
            },
            "database": {"path": str(tmp_path / "data" / "centbot.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"directory": str(tmp_path / "backups")},
            "security": {
                "credentials_file": str(tmp_path / "data" / "credentials.enc"),
                "sandbox_dir": str(tmp_path / "sandbox"),
            },
            "dashboard": {"enabled": False},
        }
    )
    return CentBotEngine(cfg)


def test_config_loads():
    cfg = Config()
    assert cfg.get("system.name") == "CENTBOT"
    assert cfg.is_dry_run()


def test_database_and_double_entry(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    journal = ActionJournal(tmp_path)
    ledger = FinanceLedger(db, journal)
    assert ledger.record_bank_reward(amount=10, currency="USD", platform="jobbi", tx_ref="tx1")
    assert not ledger.record_bank_reward(amount=10, currency="USD", platform="jobbi", tx_ref="tx1")
    assert ledger.total_profit() == 10


def test_dedup_and_priority():
    tasks = [
        {"title": "Clean CSV list", "reward_amount": 10, "fingerprint": "a", "platform": "x", "external_id": "1"},
        {"title": "Clean CSV list", "reward_amount": 10, "fingerprint": "b", "platform": "y", "external_id": "2"},
        {"title": "Different task", "reward_amount": 5, "fingerprint": "c", "platform": "x", "external_id": "3"},
    ]
    kept = DuplicateFilter(0.92).filter(tasks)
    assert len(kept) == 2
    assert score_priority({"expected_profit": 20, "reward_probability": 0.9, "payer_trust": 0.9, "estimated_hours": 1, "complexity": 0.2, "funded": 1}) > 50


def test_analysis_rejects_unprofitable(tmp_path: Path):
    journal = ActionJournal(tmp_path)
    pipe = AnalysisPipeline(
        {"min_expected_profit": 5, "min_reward_probability": 0.4, "max_estimated_hours": 8, "reject_unfunded": True, "reject_untrusted_payer_below": 0.3},
        journal,
    )
    row = pipe.analyze(
        {
            "id": "1",
            "title": "Manual CAPTCHA farm",
            "description": "bad",
            "reward_amount": 0.1,
            "funded": 0,
            "available": 1,
            "payer_trust": 0.1,
            "automation_allowed": False,
        }
    )
    assert row["status"] == "rejected"


def test_categorize_and_profit_math():
    assert categorize("Merge sorted lists in Python", "implement function", "") == "programming"
    assert expected_profit(10, 1, 0.5) == 4.0
    assert to_base(1, "EUR", "USD") == pytest.approx(1.08)


def test_executors(tmp_path: Path):
    router = TaskExecutorRouter()
    for cat in ("csv", "excel", "json_xml", "pdf", "image", "text", "programming"):
        result = router.execute({"category": cat, "title": cat, "description": cat}, tmp_path / cat)
        assert result.ok, f"{cat} failed: {result.error}"


def test_credentials_and_rate_limit(tmp_path: Path):
    store = CredentialStore(tmp_path / "creds.enc")
    store.set("jobbi", {"api_key": "secret"})
    assert store.get("jobbi")["api_key"] == "secret"
    rl = RateLimiter(per_minute=2)
    assert rl.allow() and rl.allow() and not rl.allow()


def test_platform_integrations():
    cfg = Config()
    platforms = build_platforms(cfg)
    report = verify_integrations(platforms)
    assert report["jobbi"]["ok"]
    assert report["basedagents"]["ok"]
    assert report["taskmarket"]["ok"]
    assert report["bountybook"]["ok"]
    assert report["agentizable"]["ok"]
    assert report["bountybook"]["integration"]["status"] == "demo_verified"
    assert report["agentizable"]["integration"]["status"] == "demo_verified"
    assert "openbounties" in report


def test_demo_pipeline(tmp_engine: CentBotEngine):
    report = tmp_engine.run_demo_pipeline()
    assert report["discovered"] >= 1
    assert report["eligible"] >= 1
    assert any(r.get("ok") for r in report["executed"])
    assert report["profit"] > 0
    # Parallel-capable: multiple executions allowed
    assert len(report["executed"]) >= 1
    status = tmp_engine.status()
    assert status["tasks"]["completed"] >= 1
    tmp_engine.shutdown()


def test_cycle_once(tmp_engine: CentBotEngine):
    summary = tmp_engine.cycle_once()
    assert summary["ok"]
    assert summary["cycle"] == 1
    tmp_engine.shutdown()


def test_emergency_stop(tmp_engine: CentBotEngine):
    tmp_engine.emergency.trigger("test")
    assert tmp_engine.emergency.is_active()
    summary = tmp_engine.cycle_once()
    assert summary["ok"] is False
    tmp_engine.emergency.clear()
    tmp_engine.shutdown()
