"""P0–P2 hardening: sandbox, no demo inputs, payments, inputs, requirements, pipeline, FX, browser/android wiring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from centbot.core.config import Config
from centbot.core.database import Database, utcnow
from centbot.core.engine import CentBotEngine
from centbot.core.logger import ActionJournal
from centbot.executors.router import TaskExecutorRouter
from centbot.finance.currency import convert, fx_status, refresh_rates, to_base
from centbot.finance.ledger import FinanceLedger
from centbot.finance.payment_verify import confirm_payment, is_real_tx_ref
from centbot.inputs.fetch import download_task_inputs, extract_input_urls
from centbot.platforms.base import PlatformTask
from centbot.quality.requirements import verify_against_requirements
from centbot.sandbox import isolate_file, run_python_isolated
from centbot.sandbox.isolated import sandbox_available


def test_sandbox_module_public_api(tmp_path: Path):
    assert sandbox_available()
    result = run_python_isolated(code="print('isolated-ok')", workdir=tmp_path / "sb")
    assert result["ok"]
    assert "isolated-ok" in result["stdout"]
    src = tmp_path / "secret.txt"
    src.write_text("x", encoding="utf-8")
    dest = isolate_file(src, tmp_path / "iso")
    assert dest.exists()


def test_executors_reject_missing_real_inputs(tmp_path: Path):
    router = TaskExecutorRouter(browser_enabled=True, android_enabled=False)
    for cat in ("csv", "excel", "json_xml", "pdf", "image"):
        result = router.execute({"category": cat, "title": cat, "description": ""}, tmp_path / cat)
        assert result.ok is False
        assert "missing_input" in (result.error or "") or result.error == "android_runtime_unavailable"
    # Programming without a problem statement cannot invent a solution
    prog = router.execute({"category": "programming", "title": "x", "description": ""}, tmp_path / "programming")
    assert prog.ok is False
    assert prog.error in {"codegen_failed", "missing_solution_after_codegen"} or "codegen" in (prog.error or "")


def test_executors_with_real_fixtures(tmp_path: Path):
    router = TaskExecutorRouter(browser_enabled=False, android_enabled=False)
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "input.csv").write_text("email,name\na@x.com,Ann\nA@X.com,Ann\n", encoding="utf-8")
    assert router.execute({"category": "csv", "title": "csv"}, csv_dir).ok

    text_dir = tmp_path / "text"
    text_dir.mkdir()
    result = router.execute(
        {"category": "text", "title": "Summarize", "description": "Great product. Shipping was slow. Support helped."},
        text_dir,
    )
    assert result.ok

    prog = tmp_path / "prog"
    prog.mkdir()
    (prog / "solution.py").write_text("def add(a,b):\n    return a+b\n", encoding="utf-8")
    (prog / "test_solution.py").write_text("from solution import add\n\ndef test_add():\n    assert add(1,2)==3\n", encoding="utf-8")
    assert router.execute({"category": "programming", "title": "add"}, prog).ok


def test_browser_and_android_wired_in_router():
    router = TaskExecutorRouter(browser_enabled=True, android_enabled=True)
    cats = {e.category for e in router.executors}
    assert "browser" in cats
    assert "android" in cats


def test_payment_requires_real_tx():
    assert not is_real_tx_ref("sim-abc")
    assert not is_real_tx_ref("dryrun-1")
    assert not is_real_tx_ref("arbitrary-long-ref")
    assert is_real_tx_ref("0x" + "ab" * 32)
    denied = confirm_payment({"payment_status": "settled"}, require_tx=True, verify_chain=False)
    assert denied["ok"] is False
    assert denied["reason"] == "missing_or_invalid_tx"
    no_recipient = confirm_payment(
        {"payment_status": "settled", "payment_tx_hash": "0x" + "cd" * 32, "amount": 5, "currency": "USDC"},
        require_tx=True,
        verify_chain=False,
    )
    assert no_recipient["ok"] is False
    assert no_recipient["reason"] == "recipient_required"
    ok = confirm_payment(
        {
            "payment_status": "settled",
            "payment_tx_hash": "0x" + "cd" * 32,
            "amount": 5,
            "currency": "USDC",
            "to": "0x1111111111111111111111111111111111111111",
        },
        require_tx=True,
        verify_chain=False,
    )
    assert ok["ok"] is True


def test_input_download_writes_brief(tmp_path: Path):
    task = {
        "id": "t1",
        "title": "Clean CSV",
        "description": "Normalize emails. Example file https://example.com/data/sample.csv",
        "category": "csv",
        "platform": "jobbi",
        "raw_json": {"attachments": ["https://example.com/files/input.csv"]},
    }
    urls = extract_input_urls(task)
    assert any(u.endswith(".csv") for u in urls)
    # example.com may 404; still writes brief/manifest
    manifest = download_task_inputs(task, tmp_path, timeout=5)
    assert (tmp_path / "task_brief.json").exists()
    assert (tmp_path / "input.txt").exists()
    assert "saved" in manifest


def test_requirements_check(tmp_path: Path):
    task = {
        "category": "text",
        "title": "Summarize feedback",
        "description": "Deliverable: summary.json\nWrite a concise summary.",
    }
    out = tmp_path / "summary.json"
    out.write_text(
        json.dumps({"short_summary": "Great product themes and shipping feedback", "top_words": [["themes", 1], ["shipping", 1]]}),
        encoding="utf-8",
    )
    report = verify_against_requirements(
        task,
        {"ok": True, "artifacts": [str(out)], "output": {"short_summary": "product themes shipping feedback"}},
        tmp_path,
    )
    assert report["ok"] is True, report


def test_live_fx_rates():
    rates = refresh_rates(force=True)
    assert rates["USD"] == 1.0
    assert rates["USDC"] == 1.0
    status = fx_status()
    assert "source" in status
    # EUR should convert somehow
    assert to_base(1, "EUR", "USD") > 0
    assert convert(1, "USD", "USD") == 1.0


def test_claim_execute_submit_paid_flow(tmp_path: Path):
    """Verified lifecycle with a mock platform that returns a real tx on payment check."""
    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()

    class FakePlatform:
        name = "fakeboard"
        enabled = True

        def __init__(self):
            self.claimed = False
            self.submitted = False

        def list_tasks(self):
            return [
                PlatformTask(
                    platform="fakeboard",
                    external_id="task-1",
                    title="Summarize product notes",
                    description="Deliverable: summary.json\nWrite a short product summary.",
                    reward_amount=5.0,
                    reward_currency="USDC",
                    funded=True,
                    available=True,
                    claimable=True,
                    automation_allowed=True,
                    payer_rating=0.9,
                    category_hint="text",
                    raw={"source": "fake"},
                )
            ]

        def health(self):
            return {"platform": "fakeboard", "live": True, "enabled": True, "configured": True}

        def check_automation_rules(self):
            return {"platform": "fakeboard", "automation_allowed": True, "requires_human_review": False}

        def accept_task(self, task):
            self.claimed = True
            return {"ok": True, "external_id": task.external_id}

        def submit_result(self, task, payload):
            self.submitted = True
            return {"ok": True, "status": "submitted"}

        def check_submission_status(self, submission_id):
            return {"status": "verified"}

        def check_payment(self, task_id):
            return {
                "ok": True,
                "payment": {
                    "payment_status": "settled",
                    "payment_tx_hash": "0x" + "11" * 32,
                    "amount": 5.0,
                    "currency": "USDC",
                    "to": "0x1111111111111111111111111111111111111111",
                },
            }

    fake = FakePlatform()
    cfg = Config(
        overrides={
            "system": {
                "mode": "live",
                "pid_file": str(tmp_path / "data" / "centbot.pid"),
                "emergency_stop_file": str(tmp_path / "data" / "EMERGENCY_STOP"),
                "max_parallel_tasks": 1,
            },
            "database": {"path": str(tmp_path / "data" / "centbot.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"enabled": False, "directory": str(tmp_path / "backups")},
            "security": {"credentials_file": str(tmp_path / "data" / "credentials.enc"), "rate_limit_per_minute": 100},
            "dashboard": {"enabled": False},
            "analysis": {
                "min_expected_profit": 0.01,
                "min_reward_probability": 0.1,
                "reject_unfunded": False,
                "reject_untrusted_payer_below": 0.01,
                "auto_accept": True,
                "max_estimated_hours": 24,
            },
            "platforms": {
                "jobbi": {"enabled": False},
                "basedagents": {"enabled": False},
                "taskmarket": {"enabled": False},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": False},
            },
            "finance": {
                "reconcile_payments": True,
                "require_tx_hash": True,
                "verify_on_chain": False,  # chain mocked in dedicated security tests
                "simulate_rewards_in_dry_run": False,
                "crypto_wallet_public": "0x1111111111111111111111111111111111111111",
            },
            "browser": {"enabled": False},
            "android": {"enabled": False},
        }
    )
    engine = CentBotEngine(cfg)
    engine.platforms = {"fakeboard": fake}
    engine.scanner.platforms = engine.platforms
    engine.acceptor.platforms = engine.platforms
    engine.submitter.platforms = engine.platforms
    engine.status_checker.platforms = engine.platforms
    engine.submitter.dry_run = False
    engine.acceptor.dry_run = False

    analyzed = engine.discover_and_analyze()
    assert analyzed
    eligible = [t for t in analyzed if t["status"] == "eligible"]
    assert eligible, analyzed
    row = eligible[0]

    # claim
    accept = engine.acceptor.accept({**row, "_task": fake.list_tasks()[0]})
    assert accept["ok"] and fake.claimed
    engine.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("accepted", utcnow(), row["id"]))

    # execute + submit
    result = engine.execute_task({**row, "status": "accepted", "_task": fake.list_tasks()[0]})
    assert result["ok"], result
    assert fake.submitted

    # mark submitted then reconcile paid
    engine.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("submitted", utcnow(), row["id"]))
    paid = engine.reconcile_payments()
    assert paid and paid[0]["tx_ref"].startswith("0x")
    task = engine.db.fetchone("SELECT status FROM tasks WHERE id=?", (row["id"],))
    assert task["status"] == "paid"
    assert engine.ledger.total_profit() > 0
    engine.shutdown()


def test_reconcile_rejects_synthetic_tx(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    journal = ActionJournal(tmp_path)
    ledger = FinanceLedger(db, journal)
    # Direct unit: confirm_payment path
    assert confirm_payment({"payment_status": "settled", "payment_tx_hash": "sim-1"}, require_tx=True)["ok"] is False
    assert ledger.total_profit() == 0


def test_programming_codegen_produces_autonomous_solution(tmp_path: Path):
    """Programming executor invents a solution from the task/tests (no pre-written solution.py)."""
    from centbot.executors.programming import ProgrammingExecutor

    workdir = tmp_path / "prog"
    workdir.mkdir()
    (workdir / "test_solution.py").write_text(
        "from solution import merge_sorted\n"
        "def test_merge():\n"
        "    assert merge_sorted([1, 3], [2, 4]) == [1, 2, 3, 4]\n"
        "    assert merge_sorted([], [1]) == [1]\n",
        encoding="utf-8",
    )
    task = {
        "category": "programming",
        "title": "Merge sorted lists",
        "description": "Implement merge_sorted(a, b) that merges two sorted lists.",
    }
    result = ProgrammingExecutor().execute(task, workdir)
    assert result.ok, result.error
    assert (workdir / "solution.py").exists()
    assert "merge_sorted" in (workdir / "solution.py").read_text(encoding="utf-8")
    assert result.output and result.output.get("codegen", {}).get("ok") is True
