"""Generic fallback executor + BasedAgents 409 claim mapping."""

from __future__ import annotations

from pathlib import Path

from centbot.executors.router import TaskExecutorRouter
from centbot.platforms.basedagents import _claim_http_error, _map_category
from centbot.platforms.http import PlatformHTTPError


def test_other_category_no_longer_unsupported(tmp_path: Path):
    router = TaskExecutorRouter(browser_enabled=False, android_enabled=False)
    result = router.execute(
        {
            "category": "other",
            "title": "Summarise delivery notes",
            "description": "Note one. Note two. Note three about a delay.",
            "platform": "taskmarket",
        },
        tmp_path / "work",
    )
    assert result.ok is True
    assert result.error != "unsupported_category"
    assert any(Path(a).exists() for a in result.artifacts)


def test_browser_without_steps_falls_back_to_generic(tmp_path: Path):
    router = TaskExecutorRouter(browser_enabled=True, android_enabled=False)
    result = router.execute(
        {
            "category": "browser",
            "title": "Automation scan",
            "description": "Review the revenue guard checklist and summarise findings.",
        },
        tmp_path / "browser-work",
    )
    assert result.ok is True
    assert "missing_input:browser_steps" not in str(result.error or "")


def test_basedagents_409_maps_to_already_claimed():
    exc = PlatformHTTPError("POST claim -> 409", status=409, body={"error": "conflict", "message": "already claimed"})
    r = _claim_http_error(exc, "task_abc")
    assert r["ok"] is False
    assert r["error"] == "already_claimed"
    assert r["reason"] == "already_claimed"


def test_map_unknown_basedagents_category_to_other():
    assert _map_category("automation") == "browser"
    assert _map_category("weird-new-label") == "other"
    assert _map_category("code") == "programming"
