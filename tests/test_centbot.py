"""CENTBOT live-platform and module tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
from centbot.platforms.basedagents import BasedAgentsConnector
from centbot.platforms.http import HttpClient
from centbot.platforms.jobbi import JobbiConnector
from centbot.platforms.registry import build_platforms, verify_integrations
from centbot.platforms.taskmarket import TaskMarketConnector
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
                "max_parallel_tasks": 2,
            },
            "database": {"path": str(tmp_path / "data" / "centbot.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"directory": str(tmp_path / "backups"), "enabled": False},
            "security": {
                "credentials_file": str(tmp_path / "data" / "credentials.enc"),
                "sandbox_dir": str(tmp_path / "sandbox"),
                "rate_limit_per_minute": 120,
            },
            "dashboard": {"enabled": False},
            "analysis": {
                "min_expected_profit": 0.01,
                "min_reward_probability": 0.2,
                "max_estimated_hours": 24,
                "reject_unfunded": False,
                "reject_untrusted_payer_below": 0.05,
                "auto_accept": False,
            },
            "platforms": {
                "jobbi": {"enabled": True, "base_url": "https://jobbi.org", "min_reward": 0, "limit": 5, "lane": "agent"},
                "basedagents": {"enabled": True, "base_url": "https://api.basedagents.ai", "min_usdc": 0, "limit": 5},
                "taskmarket": {"enabled": True, "base_url": "https://api.taskmarket.dev", "min_reward": 0, "limit": 5},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": True, "base_url": "https://api.agentizable.ai", "min_reward": 0},
            },
            "finance": {"simulate_rewards_in_dry_run": False, "reconcile_payments": False},
        }
    )
    return CentBotEngine(cfg)


def test_config_loads():
    cfg = Config()
    assert cfg.get("system.name") == "CENTBOT"
    assert cfg.get("platforms.jobbi.base_url") == "https://jobbi.org"
    assert cfg.get("platforms.basedagents.base_url") == "https://api.basedagents.ai"


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
        {
            "min_expected_profit": 5,
            "min_reward_probability": 0.4,
            "max_estimated_hours": 8,
            "reject_unfunded": True,
            "reject_untrusted_payer_below": 0.3,
        },
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


def test_live_jobbi_feed():
    conn = JobbiConnector({"enabled": True, "base_url": "https://jobbi.org", "lane": "agent", "limit": 3, "min_reward": 0})
    tasks = conn.list_tasks()
    assert isinstance(tasks, list)
    assert len(tasks) >= 1
    assert tasks[0].external_id
    assert tasks[0].title
    health = conn.health()
    assert health["live"] is True


def test_live_basedagents_feed():
    conn = BasedAgentsConnector({"enabled": True, "base_url": "https://api.basedagents.ai", "limit": 3, "min_usdc": 0})
    tasks = conn.list_tasks()
    assert isinstance(tasks, list)
    assert len(tasks) >= 1
    assert tasks[0].platform == "basedagents"
    assert conn.health()["live"] is True


def test_live_taskmarket_feed():
    conn = TaskMarketConnector({"enabled": True, "base_url": "https://api.taskmarket.dev", "limit": 3, "min_reward": 0})
    tasks = conn.list_tasks()
    assert isinstance(tasks, list)
    assert len(tasks) >= 1
    assert tasks[0].reward_currency == "USDC"
    assert conn.health()["live"] is True


def test_platform_integrations_live():
    cfg = Config(
        overrides={
            "platforms": {
                "bountybook": {"enabled": False},
            }
        }
    )
    platforms = build_platforms(cfg)
    report = verify_integrations(platforms)
    assert report["jobbi"]["ok"]
    assert report["basedagents"]["ok"]
    assert report["taskmarket"]["ok"]
    assert report["jobbi"]["sample_task_count"] >= 1
    assert "openbounties" not in report  # demo extra source removed


def test_live_trial_pipeline(tmp_engine: CentBotEngine):
    report = tmp_engine.run_live_trial(execute_local=True)
    assert report["discovered"] >= 1
    # Eligible depends on live market quality; discovery itself must be real
    assert isinstance(report["samples"], list)
    assert report["integrations"]["jobbi"]["ok"] or report["integrations"]["basedagents"]["ok"]
    tmp_engine.shutdown()


def test_cycle_once(tmp_engine: CentBotEngine):
    summary = tmp_engine.cycle_once()
    assert summary["ok"]
    assert summary["cycle"] == 1
    assert summary["mode"] == "dry_run"
    tmp_engine.shutdown()


def test_emergency_stop(tmp_engine: CentBotEngine):
    tmp_engine.emergency.trigger("test")
    assert tmp_engine.emergency.is_active()
    summary = tmp_engine.cycle_once()
    assert summary["ok"] is False
    tmp_engine.emergency.clear()
    tmp_engine.shutdown()


def test_http_client_user_agent():
    client = HttpClient("https://httpbin.org")
    assert "CENTBOT" in client.session.headers["User-Agent"]


def test_no_demo_fallback_when_empty():
    conn = JobbiConnector({"enabled": True, "base_url": "https://jobbi.org", "limit": 1})
    with patch.object(conn.client, "get_json", return_value={"items": []}):
        assert conn.list_tasks() == []
