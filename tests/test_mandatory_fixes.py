"""Mandatory fixes: controlled-live dry_run lock, bank vs crypto ledger, task-specific indep tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from centbot.core.config import Config
from centbot.core.database import Database
from centbot.core.engine import CentBotEngine
from centbot.core.logger import ActionJournal
from centbot.executors.codegen import (
    build_independent_tests,
    detect_task_kind,
    generate_solution,
    looks_like_lookup_table,
    run_independent_validation,
)
from centbot.executors.programming import ProgrammingExecutor
from centbot.finance.ledger import FinanceLedger
from centbot.finance.payment_verify import confirm_payment, verify_bank_payment
from centbot.sandbox.container import available_backends, select_backend


def _engine(tmp_path: Path, *, mode: str = "live", auto_accept: bool = True) -> CentBotEngine:
    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir(exist_ok=True)
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
            "analysis": {"auto_accept": auto_accept},
            "platforms": {
                "jobbi": {"enabled": False},
                "basedagents": {"enabled": False},
                "taskmarket": {"enabled": False},
                "bountybook": {"enabled": False},
                "agentizable": {"enabled": False},
            },
            "finance": {
                "reconcile_payments": True,
                "crypto_wallet_public": "0x1111111111111111111111111111111111111111",
                "bank_iban": "DE89370400440532013000",
                "verify_on_chain": True,
            },
            "browser": {"enabled": False},
            "android": {"enabled": False},
        }
    )
    return CentBotEngine(cfg)


def test_controlled_live_forces_dry_run_even_if_config_live(tmp_path: Path):
    engine = _engine(tmp_path, mode="live", auto_accept=True)
    assert engine.config.is_live()

    accept_calls = []
    submit_calls = []
    pay_calls = []

    class Fake:
        name = "fake"
        enabled = True

        def list_tasks(self):
            return []

        def health(self):
            return {"platform": "fake", "live": True, "ok": True, "enabled": True, "configured": True}

        def check_automation_rules(self):
            return {"platform": "fake", "automation_allowed": True, "requires_human_review": False}

        def accept_task(self, task):
            accept_calls.append(task)
            return {"ok": True}

        def submit_result(self, task, payload):
            submit_calls.append(payload)
            return {"ok": True}

        def check_payment(self, task_id):
            pay_calls.append(task_id)
            return {"payment_status": "settled", "payment_tx_hash": "0x" + "ab" * 32, "to": "0x1111111111111111111111111111111111111111", "amount": 1, "currency": "USDC"}

    fake = Fake()
    engine.platforms = {"fake": fake}
    engine.scanner.platforms = engine.platforms
    engine.acceptor.platforms = engine.platforms
    engine.submitter.platforms = engine.platforms

    engine.enter_controlled_mode()
    assert engine.config.is_dry_run()
    assert engine.acceptor.dry_run is True
    assert engine.submitter.dry_run is True

    # Even direct accept/submit go through dry_run gates
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("t1", "fake", "ext-1", "x", "y", "text", "eligible", 1.0, "USDC", 50),
    )
    row = engine.db.fetchone("SELECT * FROM tasks WHERE id=?", ("t1",))
    acc = engine.acceptor.accept({**row, "status": "eligible", "_task": MagicMock()})
    assert acc.get("mode") == "dry_run"
    assert accept_calls == []

    sub = engine.submitter.submit({**row, "platform": "fake", "_task": MagicMock()}, {"x": 1})
    assert sub.get("mode") == "dry_run"
    assert submit_calls == []

    paid = engine.reconcile_payments()
    assert paid == []
    assert pay_calls == []  # controlled blocks reconcile before platform payment calls

    report = engine.run_live_trial(execute_local=False, controlled=True)
    engine.shutdown()
    assert report["mode"] == "dry_run"
    assert report["claims_allowed"] is False
    assert report["verification"]["external_accept_blocked"] is True
    assert report["verification"]["external_submit_blocked"] is True
    assert report["verification"]["external_payment_booking_blocked"] is True


def test_cli_controlled_live_overrides_mode_live(tmp_path: Path, monkeypatch):
    from centbot import __main__ as cli

    evidence = tmp_path / "ev.json"
    # Minimal: patch CentBotEngine.run_live_trial to avoid network
    calls = {}

    class FakeEngine:
        def __init__(self, config):
            calls["mode_at_init"] = config.get("system.mode")
            self.config = config
            self.acceptor = MagicMock(dry_run=config.is_dry_run())
            self.submitter = MagicMock(dry_run=config.is_dry_run())
            self._controlled_mode = False

        def enter_controlled_mode(self):
            self.config.force_dry_run()
            self.acceptor.dry_run = True
            self.submitter.dry_run = True
            self._controlled_mode = True
            calls["controlled"] = True

        def run_live_trial(self, execute_local=True, controlled=True):
            calls["trial_controlled"] = controlled
            return {
                "mode": self.config.get("system.mode"),
                "claims_allowed": False,
                "acceptor_dry_run": True,
                "submitter_dry_run": True,
                "sandbox": {},
                "integrations": {"jobbi": {"ok": True, "sample_task_count": 1}},
                "discovered": 1,
                "eligible": 0,
                "samples": [],
                "executed": [],
                "verification": {
                    "live_discovery": True,
                    "external_accept_blocked": True,
                    "external_submit_blocked": True,
                    "external_payment_booking_blocked": True,
                },
                "payments": [],
            }

        def shutdown(self):
            return None

    monkeypatch.setattr(cli, "CentBotEngine", FakeEngine)
    rc = cli.main(["--controlled-live", "--mode", "live", "--evidence-out", str(evidence)])
    assert rc == 0
    assert calls["mode_at_init"] == "dry_run"
    assert calls["controlled"] is True
    assert evidence.exists()
    data = evidence.read_text(encoding="utf-8")
    assert '"mode": "dry_run"' in data


def test_bank_vs_crypto_ledger_and_duplicates(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    journal = ActionJournal(tmp_path)
    ledger = FinanceLedger(db, journal, wallet_public="0xabc")

    assert ledger.record_crypto_reward(amount=5, currency="USDC", platform="x", tx_ref="0x" + "aa" * 32)
    assert ledger.record_crypto_reward(amount=5, currency="USDC", platform="x", tx_ref="0x" + "aa" * 32) is False
    assert ledger.record_bank_reward(amount=20, currency="EUR", platform="y", tx_ref="wise-tx-1")
    assert ledger.record_bank_reward(amount=20, currency="EUR", platform="y", tx_ref="wise-tx-1") is False

    kinds = {r["kind"] for r in ledger.income_history()}
    assert "crypto" in kinds and "bank" in kinds
    bals = ledger.balances()
    assert bals["bank"] > 0 and bals["crypto"] > 0
    assert bals["profit"] == ledger.total_profit()
    assert ledger.total_profit() > 0


def test_engine_reconcile_routes_bank_to_bank_ledger(tmp_path: Path):
    from centbot.finance.bank_providers import StaticBankProvider

    engine = _engine(tmp_path, mode="dry_run", auto_accept=False)
    engine.config.set("finance.bank_iban", "DE89370400440532013000")
    engine._bank_provider = StaticBankProvider(
        {
            "SEPA-ENG-1": {
                "id": "wise-engine-1",
                "status": "completed",
                "amount": 50.0,
                "currency": "EUR",
                "destination_iban": "DE89370400440532013000",
            }
        }
    )
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("tb", "bankplat", "ext-b", "Bank job", "", "text", "submitted", 50.0, "EUR", 50),
    )

    class BankPlat:
        name = "bankplat"
        enabled = True

        def check_payment(self, task_id):
            return {
                "method": "wise",
                "payment_status": "settled",
                "bank_reference": "SEPA-ENG-1",
                "amount": 50.0,
                "currency": "EUR",
                "provider": "wise",
                "provider_evidence": {
                    "id": "platform-forged",
                    "status": "completed",
                    "amount": 50.0,
                    "currency": "EUR",
                    "destination_iban": "DE89370400440532013000",
                },
            }

    engine.platforms = {"bankplat": BankPlat()}
    updates = engine.reconcile_payments()
    assert updates and updates[0]["method"] == "bank"
    row = engine.db.fetchone("SELECT * FROM income WHERE tx_ref=?", ("wise-engine-1",))
    assert row is not None
    assert row["kind"] == "bank"
    assert engine.ledger.record_bank_reward(amount=50, currency="EUR", platform="bankplat", tx_ref="wise-engine-1") is False
    assert engine.reconcile_payments() == []
    engine.shutdown()


def test_bank_rejects_platform_settled_without_provider():
    out = verify_bank_payment(
        {
            "method": "bank",
            "payment_status": "settled",
            "bank_reference": "SEPA-ONLY-1",
            "amount": 10,
            "currency": "EUR",
        },
        expected_iban="DE89370400440532013000",
        expected_amount=10,
        expected_currency="EUR",
    )
    assert out["ok"] is False
    assert out["reason"] == "bank_provider_not_configured"


def test_independent_tests_are_task_specific_not_generic_add(tmp_path: Path):
    # Unknown task kind → insufficient coverage (no generic add assumption)
    unknown = build_independent_tests(
        {"title": "Obfuscate bytes", "description": "Implement transform(data) somehow"},
        "from solution import transform\ndef test_t():\n    assert transform(1) == 1\n",
    )
    assert unknown["ok"] is False
    assert unknown["error"] == "insufficient_independent_coverage"
    assert detect_task_kind({"title": "Obfuscate", "description": "transform"}, "def transform") is None

    # merge_sorted gets property tests
    merge = build_independent_tests(
        {"title": "Merge sorted lists", "description": "Implement merge_sorted(a,b)"},
        "from solution import merge_sorted\ndef test_v():\n    assert merge_sorted([1],[2])==[1,2]\n",
    )
    assert merge["ok"] is True
    assert "sorted(a + b)" in merge["code"]

    workdir = tmp_path / "m"
    workdir.mkdir()
    (workdir / "test_solution.py").write_text(
        "from solution import merge_sorted\ndef test_v():\n    assert merge_sorted([1,3],[2])==[1,2,3]\n",
        encoding="utf-8",
    )
    # Correct solution
    (workdir / "solution.py").write_text(
        "def merge_sorted(a,b):\n"
        " i=j=0; out=[]\n"
        " while i<len(a) and j<len(b):\n"
        "  if a[i]<=b[j]: out.append(a[i]); i+=1\n"
        "  else: out.append(b[j]); j+=1\n"
        " out.extend(a[i:]); out.extend(b[j:]); return out\n",
        encoding="utf-8",
    )
    assert run_independent_validation(
        workdir,
        {"title": "Merge sorted", "description": "merge_sorted"},
        (workdir / "test_solution.py").read_text(encoding="utf-8"),
    )["ok"]

    # Overfit / lookup table rejected
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "solution.py").write_text(
        "def merge_sorted(*args, **kwargs):\n"
        "    if args == ([1,3],[2]):\n"
        "        return [1,2,3]\n"
        "    if args == ([1],[2]):\n"
        "        return [1,2]\n",
        encoding="utf-8",
    )
    assert looks_like_lookup_table((bad / "solution.py").read_text(encoding="utf-8"))
    assert run_independent_validation(
        bad,
        {"title": "Merge sorted", "description": "merge_sorted"},
        "assert merge_sorted([1,3],[2])==[1,2,3]",
    )["ok"] is False

    # Wrong algorithm fails independent suite
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    (wrong / "solution.py").write_text("def merge_sorted(a,b):\n    return a + b\n", encoding="utf-8")
    assert run_independent_validation(
        wrong,
        {"title": "Merge sorted", "description": "merge_sorted"},
        "",
    )["ok"] is False


def test_programming_blocks_when_independent_coverage_missing(tmp_path: Path):
    workdir = tmp_path / "prog"
    workdir.mkdir()
    (workdir / "test_solution.py").write_text(
        "from solution import transform\ndef test_t():\n    assert transform(1)==1\n",
        encoding="utf-8",
    )
    (workdir / "solution.py").write_text("def transform(x):\n    return x\n", encoding="utf-8")
    result = ProgrammingExecutor().execute(
        {"category": "programming", "title": "transform", "description": "Implement transform"},
        workdir,
    )
    assert result.ok is False
    assert "insufficient" in (result.error or "") or "independent" in (result.error or "")


def test_generate_solution_merge_ok(tmp_path: Path):
    workdir = tmp_path / "g"
    workdir.mkdir()
    (workdir / "test_solution.py").write_text(
        "from solution import merge_sorted\ndef test_v():\n    assert merge_sorted([1],[2])==[1,2]\n",
        encoding="utf-8",
    )
    meta = generate_solution(
        {"title": "Merge sorted lists", "description": "Implement merge_sorted(a, b)"},
        workdir,
    )
    assert meta["ok"] is True
    assert meta["independent"]["ok"] is True


def test_docker_windows_backend_status_report(tmp_path: Path):
    backends = available_backends()
    selected = select_backend("auto")
    # On this Linux agent we expect unshare_container; Docker/Windows may be unavailable
    assert selected in {"unshare_container", "docker", "podman", "restrictor_only"}
    assert isinstance(backends.get("windows_vm"), bool)
    assert backends["windows_vm"] is False  # never auto-claimed on Linux
    report = {
        "docker": backends.get("docker"),
        "podman": backends.get("podman"),
        "unshare_container": backends.get("unshare_container"),
        "windows_vm": backends.get("windows_vm"),
        "selected": selected,
    }
    (tmp_path / "sandbox-backends.json").write_text(str(report), encoding="utf-8")
    assert report["selected"]
