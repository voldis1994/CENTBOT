"""P0/P1 remaining: container sandbox, independent codegen, multi-chain/bank, controlled live."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from centbot.executors.codegen import generate_solution, looks_like_lookup_table, run_independent_validation
from centbot.executors.programming import ProgrammingExecutor
from centbot.finance.payment_verify import (
    confirm_payment,
    resolve_chain,
    verify_bank_payment,
    verify_on_chain,
)
from centbot.sandbox.container import available_backends, select_backend
from centbot.sandbox.isolated import run_python_isolated, sandbox_available, sandbox_backend_info


def test_strict_container_backend_selected():
    backends = available_backends()
    assert backends["unshare_container"] or backends["docker"] or backends["podman"]
    selected = select_backend("auto")
    assert selected in {"unshare_container", "docker", "podman"}
    info = sandbox_backend_info()
    assert info["selected"] == selected


def test_sandbox_runs_inside_container(tmp_path: Path):
    assert sandbox_available()
    result = run_python_isolated(code="print('container-ok')", workdir=tmp_path / "sb", timeout=30)
    assert result["ok"]
    assert result.get("container") is True
    assert "container-ok" in (result.get("stdout") or "")
    assert result.get("backend") in {"unshare_container", "docker", "podman"}


def test_container_blocks_host_escape_and_network(tmp_path: Path):
    net = run_python_isolated(code="import socket", workdir=tmp_path / "net", timeout=30)
    assert net.get("ok") is False

    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    fs = run_python_isolated(
        code=f"print(open({str(secret)!r}).read())",
        workdir=tmp_path / "fs",
        timeout=30,
    )
    assert fs.get("ok") is False


def test_codegen_rejects_lookup_table_overfit(tmp_path: Path):
    bad = (
        "def add(*args, **kwargs):\n"
        "    # Literal cases derived from unit tests\n"
        "    if args == (1, 2):\n"
        "        return 3\n"
        "    if args == (4, 5):\n"
        "        return 9\n"
    )
    assert looks_like_lookup_table(bad) is True
    workdir = tmp_path / "overfit"
    workdir.mkdir()
    (workdir / "solution.py").write_text(bad, encoding="utf-8")
    (workdir / "test_solution.py").write_text(
        "from solution import add\ndef test_add():\n    assert add(1,2)==3\n",
        encoding="utf-8",
    )
    indep = run_independent_validation(
        workdir,
        {"title": "add", "description": "implement add"},
        (workdir / "test_solution.py").read_text(encoding="utf-8"),
    )
    assert indep["ok"] is False
    assert indep["error"] == "lookup_table_rejected"


def test_codegen_independent_tests_for_merge_sorted(tmp_path: Path):
    workdir = tmp_path / "prog"
    workdir.mkdir()
    (workdir / "test_solution.py").write_text(
        "from solution import merge_sorted\n"
        "def test_visible():\n"
        "    assert merge_sorted([1,3],[2]) == [1,2,3]\n",
        encoding="utf-8",
    )
    meta = generate_solution(
        {"title": "Merge sorted lists", "description": "Implement merge_sorted(a, b)"},
        workdir,
    )
    assert meta["ok"] is True
    assert meta.get("independent", {}).get("ok") is True
    result = ProgrammingExecutor().execute(
        {"category": "programming", "title": "Merge sorted lists", "description": "Implement merge_sorted"},
        workdir,
    )
    assert result.ok
    assert result.output["independent"]["ok"] is True


def test_resolve_chain_multi_network():
    assert resolve_chain("eip155:1")["name"] == "ethereum"
    assert resolve_chain("arbitrum")["chain_id"] == 42161
    assert resolve_chain("polygon")["rpc"]
    assert "USDC" in resolve_chain("optimism")["tokens"]


def test_verify_on_chain_uses_network_token(tmp_path: Path):
    tx = "0x" + "22" * 32
    wallet = "0x3333333333333333333333333333333333333333"
    # Ethereum USDC transfer
    amount_atomic = 2_500_000
    receipt = {
        "status": "0x1",
        "blockNumber": "0x10",
        "logs": [
            {
                "address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x" + "00" * 32,
                    "0x" + "00" * 12 + wallet[2:],
                ],
                "data": hex(amount_atomic),
            }
        ],
    }

    def fake_rpc(method, params, rpc_url):
        assert "ethereum" in rpc_url or "publicnode" in rpc_url
        if method == "eth_getTransactionReceipt":
            return receipt
        if method == "eth_blockNumber":
            return "0x20"
        raise AssertionError(method)

    with patch("centbot.finance.payment_verify._rpc", side_effect=fake_rpc):
        out = verify_on_chain(
            tx,
            expected_to=wallet,
            expected_amount=2.5,
            currency="USDC",
            network="ethereum",
            min_confirmations=1,
        )
    assert out["ok"] is True
    assert out["network"] == "ethereum"


def test_bank_payment_verification_separate_from_crypto():
    ok = verify_bank_payment(
        {
            "method": "sepa",
            "payment_status": "settled",
            "bank_reference": "SEPA-2026-998877",
            "iban": "DE89 3704 0044 0532 0130 00",
            "amount": 120.5,
            "currency": "EUR",
            "provider": "wise",
        }
    )
    assert ok["ok"] is True
    assert ok["method"] == "bank"

    crypto_on_bank = confirm_payment(
        {
            "method": "bank",
            "payment_status": "settled",
            "bank_reference": "SEPA-1",
            "iban": "DE89370400440532013000",
            "amount": 1,
            "currency": "USDC",
        }
    )
    assert crypto_on_bank["ok"] is False
    assert crypto_on_bank["reason"] == "crypto_currency_on_bank_rail"

    crypto = confirm_payment(
        {
            "payment_status": "settled",
            "payment_tx_hash": "0x" + "cd" * 32,
            "to": "0x1111111111111111111111111111111111111111",
            "network": "optimism",
            "amount": 1,
            "currency": "USDC",
        },
        verify_chain=False,
    )
    assert crypto["ok"] is True
    assert crypto["method"] == "crypto"
    assert crypto["network"] in {"optimism", "eip155:10"} or "optimism" in str(crypto.get("network"))


def test_controlled_live_trial_report(tmp_path: Path):
    from centbot.core.config import Config
    from centbot.core.engine import CentBotEngine

    for d in ("data", "logs", "backups", "sandbox"):
        (tmp_path / d).mkdir()
    cfg = Config(
        overrides={
            "system": {
                "mode": "dry_run",
                "pid_file": str(tmp_path / "data" / "centbot.pid"),
                "emergency_stop_file": str(tmp_path / "data" / "EMERGENCY_STOP"),
                "max_parallel_tasks": 1,
            },
            "database": {"path": str(tmp_path / "data" / "centbot.db")},
            "logging": {"directory": str(tmp_path / "logs")},
            "backup": {"enabled": False, "directory": str(tmp_path / "backups")},
            "security": {"credentials_file": str(tmp_path / "data" / "credentials.enc")},
            "dashboard": {"enabled": False},
            "platforms": {"bountybook": {"enabled": False}},
            "finance": {"reconcile_payments": True, "simulate_rewards_in_dry_run": False},
            "browser": {"enabled": False},
            "android": {"enabled": False},
        }
    )
    engine = CentBotEngine(cfg)
    report = engine.run_live_trial(execute_local=False)
    engine.shutdown()
    assert report["controlled"] is True
    assert report["claims_allowed"] is False
    assert report["discovered"] >= 1
    assert report["verification"]["live_discovery"] is True
    assert report["verification"]["reward_received"] is False
    assert report["verification"]["reward_blocker"] == "dry_run_no_claim"
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"verification": report["verification"]}, indent=2), encoding="utf-8")
    assert evidence.exists()
