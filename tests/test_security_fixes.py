"""Fixes for gitignore sandbox leak, on-chain payment verify, SSRF inputs, requirements, profit."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from centbot.core.database import Database
from centbot.core.logger import ActionJournal
from centbot.finance.ledger import FinanceLedger
from centbot.finance.payment_verify import confirm_payment, is_real_tx_ref, verify_on_chain
from centbot.inputs.fetch import download_task_inputs, safe_download, validate_url_destination
from centbot.quality.requirements import verify_against_requirements
from centbot.sandbox.isolated import sandbox_available


def test_sandbox_package_is_tracked_and_importable():
    assert sandbox_available()
    root = Path(__file__).resolve().parents[1]
    assert (root / "centbot" / "sandbox" / "isolated.py").exists()
    # Root runtime sandbox dir may exist; package must not be ignored conceptually
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "/sandbox/" in gitignore
    assert "\nsandbox/\n" not in gitignore


def test_rejects_non_hash_payment_refs():
    assert not is_real_tx_ref("platform-task-1-payout")
    assert not is_real_tx_ref("totally-long-enough")
    assert not is_real_tx_ref("0xdead")
    assert is_real_tx_ref("0x" + "ab" * 32)


def test_confirm_payment_requires_on_chain_when_enabled():
    # Valid hash shape but unknown on chain -> not ok
    result = confirm_payment(
        {"payment_status": "settled", "payment_tx_hash": "0x" + "ab" * 32, "amount": 1, "currency": "USDC"},
        require_tx=True,
        expected_wallet="0x1111111111111111111111111111111111111111",
        verify_chain=True,
    )
    assert result["ok"] is False
    assert result["reason"] in {"tx_not_found_or_pending", "rpc_error", "transfer_mismatch", "tx_reverted", "unmined"}


def test_confirm_payment_platform_only_when_chain_disabled():
    result = confirm_payment(
        {"payment_status": "settled", "payment_tx_hash": "0x" + "cd" * 32, "amount": 5, "currency": "USDC"},
        require_tx=True,
        verify_chain=False,
    )
    assert result["ok"] is True


def test_on_chain_verify_matches_mock_receipt():
    tx = "0x" + "11" * 32
    wallet = "0x2222222222222222222222222222222222222222"
    # USDC transfer log: topic0 Transfer, topic1 from, topic2 to, data amount 5_000000
    amount_atomic = 5_000_000
    receipt = {
        "status": "0x1",
        "blockNumber": "0x10",
        "logs": [
            {
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
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
        if method == "eth_getTransactionReceipt":
            return receipt
        if method == "eth_blockNumber":
            return "0x20"
        raise AssertionError(method)

    with patch("centbot.finance.payment_verify._rpc", side_effect=fake_rpc):
        out = verify_on_chain(tx, expected_to=wallet, expected_amount=5.0, currency="USDC", min_confirmations=1)
    assert out["ok"] is True
    assert out["transfer"]["amount"] == 5.0
    assert out["confirmations"] >= 1


def test_ssrf_blocks_localhost_and_metadata():
    assert validate_url_destination("http://127.0.0.1/secret")["ok"] is False
    assert validate_url_destination("https://localhost/x")["ok"] is False
    assert validate_url_destination("https://169.254.169.254/latest/meta-data")["ok"] is False
    assert validate_url_destination("http://example.com/a.csv")["ok"] is False  # http blocked
    assert validate_url_destination("https://example.com/a.csv")["ok"] is True


def test_safe_download_enforces_size(tmp_path: Path):
    dest = tmp_path / "big.bin"

    class FakeResp:
        status_code = 200
        headers = {"Content-Length": "100"}
        is_redirect = False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield b"x" * 50
            yield b"y" * 50

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("centbot.inputs.fetch.requests.get", return_value=FakeResp()):
        with patch("centbot.inputs.fetch.validate_url_destination", return_value={"ok": True, "host": "example.com", "ips": ["1.2.3.4"]}):
            result = safe_download("https://example.com/x", dest, max_bytes=40)
    assert result["ok"] is False
    assert result["error"] == "content_too_large"


def test_requirements_fail_closed_without_structure(tmp_path: Path):
    task = {
        "category": "other",
        "title": "Vague work",
        "description": "- Completely rewrite the entire marketing narrative carefully\n- Ensure brand voice remains consistent throughout",
    }
    out = tmp_path / "notes.txt"
    out.write_text("hello world", encoding="utf-8")
    report = verify_against_requirements(task, {"ok": True, "artifacts": [str(out)], "output": "hello"}, tmp_path)
    assert report["ok"] is False
    assert any("no_structural_constraints_extracted" in i or "unverified_requirement" in i for i in report["issues"])


def test_requirements_pass_with_structural_deliverable(tmp_path: Path):
    task = {
        "category": "text",
        "title": "Summarize",
        "description": "Deliverable: summary.json\nExactly 2 lines.\nEach 3-6 words.",
    }
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"short_summary": "Alpha beta gamma. Delta epsilon zeta."}), encoding="utf-8")
    txt = tmp_path / "out.txt"
    txt.write_text("Alpha beta gamma\nDelta epsilon zeta\n", encoding="utf-8")
    report = verify_against_requirements(
        task,
        {"ok": True, "artifacts": [str(summary), str(txt)], "output": {"short_summary": "ok"}},
        tmp_path,
    )
    assert report["ok"] is True, report


def test_withdrawal_does_not_reduce_profit(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    journal = ActionJournal(tmp_path)
    ledger = FinanceLedger(db, journal)
    assert ledger.record_crypto_reward(amount=10, currency="USDC", platform="x", tx_ref="0x" + "aa" * 32)
    wid = ledger.request_withdrawal(4, "USDC", "0xabc")
    assert ledger.approve_withdrawal(wid)
    assert ledger.total_profit() == pytest.approx(10.0)
    assert ledger.cash_balance() == pytest.approx(6.0)
