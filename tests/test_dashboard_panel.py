"""Control panel serves Latvian UI and honest status payload."""

from __future__ import annotations

from pathlib import Path

from centbot.core.config import Config
from centbot.core.engine import CentBotEngine
from centbot.dashboard.app import DASHBOARD_HTML, create_dashboard


def test_panel_html_matches_mockup_structure():
    html = DASHBOARD_HTML
    assert "CENTBOT" in html
    assert "Autonomā darba stacija" in html
    assert "Pārskats" in html
    assert "Aktīvie uzdevumi" in html
    assert "Banka" in html and "Kripto" in html
    assert "Global Discovery" in html
    assert "Brīdinājumi un darbības" in html
    assert "BANKA + CRYPTO" in html
    assert "/api/status" in html


def test_status_payload_has_panel_fields(tmp_path: Path):
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
            "browser": {"enabled": False},
            "android": {"enabled": False},
            "finance": {"simulate_rewards_in_dry_run": False},
        }
    )
    engine = CentBotEngine(cfg)
    engine.db.add_alert("warning", "Test alert", source="test")
    st = engine.status()
    assert "finance" in st and "bank" in st["finance"] and "crypto" in st["finance"]
    assert st["finance"]["profit"] == 0 or float(st["finance"]["profit"]) == 0
    assert "active_tasks" in st
    assert "live_readiness" in st
    assert "journal" in st
    assert "discovery" in st
    assert any(a["message"] == "Test alert" for a in st["alerts"])
    assert engine.acknowledge_alert(st["alerts"][0]["id"]) is True
    app = create_dashboard(engine.status, lambda: None, ack_alert=engine.acknowledge_alert)
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Autonom" in r.data
    s = client.get("/api/status")
    assert s.status_code == 200
    body = s.get_json()
    assert body["mode"] == "dry_run"
    assert body["live"] is False
    engine.shutdown()
