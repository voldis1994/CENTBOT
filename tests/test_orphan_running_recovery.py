"""Orphan running rows (DB=running, pool empty) must recover quickly after START."""

from __future__ import annotations

from pathlib import Path

from centbot.core.config import Config
from centbot.core.database import utcnow
from centbot.core.engine import CentBotEngine
from centbot.quality.automatable import assess_automatable


def _engine(tmp_path: Path) -> CentBotEngine:
    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()
    cfg = Config(
        overrides={
            "system": {
                "mode": "dry_run",
                "cycle_interval_seconds": 30,
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
            "browser": {"enabled": False},
            "android": {"enabled": False},
            "finance": {"simulate_rewards_in_dry_run": False},
        }
    )
    return CentBotEngine(cfg)


def test_orphan_running_reset_on_first_cycles(tmp_path: Path):
    engine = _engine(tmp_path)
    now = utcnow()
    engine.db.upsert_task(
        {
            "id": "t-orphan",
            "platform": "taskmarket",
            "external_id": "x1",
            "title": "stuck game",
            "status": "running",
            "priority": 50,
            "created_at": now,
            "updated_at": now,
        }
    )
    engine._cycles = 0
    report = engine._recover_stuck_tasks()
    assert report["orphan_reset"] >= 1
    row = engine.db.fetchone("SELECT status FROM tasks WHERE id=?", ("t-orphan",))
    assert row["status"] == "needs_repair"
    engine.shutdown()


def test_multiplayer_game_not_automatable():
    out = assess_automatable(
        {
            "title": "Build a Fun Multiplayer Strategy Game for Agents AND Humans",
            "description": "Turn-based, 2-4 players with a public URL and HTTP/JSON API.",
        }
    )
    assert out["automatable"] is False
    assert out["primary_reason"] == "requires_hosted_multiplayer"


def test_idle_reason_when_no_claimables(tmp_path: Path):
    engine = _engine(tmp_path)
    engine._running = True
    funnel = engine._task_funnel()
    reason = engine._idle_reason(launched=0, funnel=funnel, readiness={"ready": True})
    assert reason == "no_claimable_tasks"
    engine.shutdown()
