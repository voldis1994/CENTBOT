"""End-to-end payment system checklist: bank API proof, on-chain crypto, balances, duplicates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from centbot.core.config import Config
from centbot.core.database import Database
from centbot.core.engine import CentBotEngine
from centbot.core.logger import ActionJournal
from centbot.finance.bank_providers import StaticBankProvider
from centbot.finance.ledger import FinanceLedger
from centbot.finance.payment_verify import confirm_payment, verify_bank_payment, verify_on_chain


IBAN = "DE89370400440532013000"
WALLET = "0x1111111111111111111111111111111111111111"


def test_bank_rejects_settled_reference_and_platform_evidence():
    payload = {
        "method": "wise",
        "payment_status": "settled",
        "bank_reference": "SEPA-PLAT-1",
        "iban": IBAN,
        "amount": 10,
        "currency": "EUR",
        "provider_evidence": {  # must be ignored even if present
            "id": "fake-from-platform",
            "status": "completed",
            "amount": 10,
            "currency": "EUR",
            "destination_iban": IBAN,
        },
    }
    no_api = verify_bank_payment(payload, expected_iban=IBAN, expected_amount=10, expected_currency="EUR")
    assert no_api["ok"] is False
    assert no_api["reason"] in {"bank_provider_not_configured", "provider_evidence_required"}

    # Even with expected fields, embedded blob is not used — API required
    still = verify_bank_payment(
        payload,
        expected_iban=IBAN,
        expected_amount=10,
        expected_currency="EUR",
        provider_client=None,
    )
    assert still["ok"] is False


def test_bank_accepts_independent_provider_api_match():
    provider = StaticBankProvider(
        {
            "SEPA-OK-1": {
                "id": "wise-independent-99",
                "status": "completed",
                "amount": 42.5,
                "currency": "EUR",
                "destination_iban": IBAN,
            }
        }
    )
    out = verify_bank_payment(
        {
            "method": "sepa",
            "payment_status": "settled",
            "bank_reference": "SEPA-OK-1",
            "amount": 42.5,
            "currency": "EUR",
            "provider": "wise",
            # Platform tries to inject a different tx — must be ignored
            "provider_evidence": {
                "id": "platform-lie",
                "status": "completed",
                "amount": 42.5,
                "currency": "EUR",
                "destination_iban": IBAN,
            },
        },
        expected_amount=42.5,
        expected_currency="EUR",
        expected_iban=IBAN,
        provider_client=provider,
    )
    assert out["ok"] is True
    assert out["provider_tx_id"] == "wise-independent-99"
    assert out["source"] == "provider_api"
    assert out["iban"].replace(" ", "") == IBAN


def test_bank_mismatch_iban_amount_currency():
    provider = StaticBankProvider(
        {
            "SEPA-X": {
                "id": "tx-1",
                "status": "completed",
                "amount": 10,
                "currency": "EUR",
                "destination_iban": "LT121000011101001000",
            }
        }
    )
    bad_iban = verify_bank_payment(
        {"method": "bank", "payment_status": "settled", "bank_reference": "SEPA-X", "amount": 10, "currency": "EUR"},
        expected_amount=10,
        expected_currency="EUR",
        expected_iban=IBAN,
        provider_client=provider,
    )
    assert bad_iban["ok"] is False
    assert bad_iban["reason"] == "provider_iban_mismatch"

    provider2 = StaticBankProvider(
        {
            "SEPA-Y": {
                "id": "tx-2",
                "status": "completed",
                "amount": 9,
                "currency": "EUR",
                "destination_iban": IBAN,
            }
        }
    )
    bad_amt = verify_bank_payment(
        {"method": "bank", "payment_status": "settled", "bank_reference": "SEPA-Y", "amount": 10, "currency": "EUR"},
        expected_amount=10,
        expected_currency="EUR",
        expected_iban=IBAN,
        provider_client=provider2,
    )
    assert bad_amt["reason"] == "provider_amount_mismatch"


def test_crypto_requires_on_chain_not_platform_only():
    denied = confirm_payment(
        {
            "payment_status": "settled",
            "payment_tx_hash": "0x" + "ab" * 32,
            "to": WALLET,
            "amount": 5,
            "currency": "USDC",
        },
        expected_wallet=WALLET,
        expected_amount=5,
        verify_chain=False,
    )
    assert denied["ok"] is False
    assert denied["reason"] == "on_chain_verification_required"


def test_crypto_on_chain_matches_recipient_amount_token_confirmations():
    tx = "0x" + "33" * 32
    amount_atomic = 7_500_000
    receipt = {
        "status": "0x1",
        "blockNumber": "0x10",
        "logs": [
            {
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x" + "00" * 32,
                    "0x" + "00" * 12 + WALLET[2:],
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
        out = confirm_payment(
            {
                "payment_status": "settled",
                "payment_tx_hash": tx,
                "to": WALLET,
                "amount": 7.5,
                "currency": "USDC",
                "network": "base",
            },
            expected_wallet=WALLET,
            expected_amount=7.5,
            min_confirmations=1,
            verify_chain=True,
        )
    assert out["ok"] is True
    assert out["method"] == "crypto"
    assert out["transfer"]["amount"] == 7.5
    assert out["transfer"]["to"].lower() == WALLET.lower()
    assert out["confirmations"] >= 1


def test_ledger_separate_balances_profit_duplicates_and_manual_withdrawal(tmp_path: Path):
    db = Database(tmp_path / "pay.db")
    journal = ActionJournal(tmp_path)
    ledger = FinanceLedger(db, journal, default_currency="USD")

    assert ledger.record_bank_reward(amount=100, currency="USD", platform="jobbi", tx_ref="bank-1")
    assert ledger.record_bank_reward(amount=100, currency="USD", platform="jobbi", tx_ref="bank-1") is False
    assert ledger.record_crypto_reward(amount=25, currency="USDC", platform="ba", tx_ref="0x" + "cc" * 32)
    assert ledger.record_crypto_reward(amount=25, currency="USDC", platform="ba", tx_ref="0x" + "cc" * 32) is False

    balances = ledger.balances()
    assert balances["bank"] == pytest.approx(100.0)
    assert balances["crypto"] == pytest.approx(25.0)
    assert balances["profit"] == pytest.approx(125.0)

    wid = ledger.request_withdrawal(40, "USD", "iban:" + IBAN)
    # Manual approval required — pending does not reduce profit
    assert ledger.total_profit() == pytest.approx(125.0)
    assert ledger.approve_withdrawal(wid)
    assert ledger.total_profit() == pytest.approx(125.0)  # withdrawals excluded from profit
    assert ledger.cash_balance() == pytest.approx(85.0)
    assert ledger.bank_balance() == pytest.approx(100.0)
    assert ledger.crypto_balance() == pytest.approx(25.0)


def test_engine_reconcile_bank_and_crypto_rails(tmp_path: Path):
    for d in ("data", "logs", "backups"):
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
            "finance": {
                "reconcile_payments": True,
                "verify_on_chain": True,
                "crypto_wallet_public": WALLET,
                "bank_iban": IBAN,
                "min_confirmations": 1,
            },
            "browser": {"enabled": False},
            "android": {"enabled": False},
        }
    )
    engine = CentBotEngine(cfg)
    engine._bank_provider = StaticBankProvider(
        {
            "SEPA-ENG-2": {
                "id": "wise-api-77",
                "status": "completed",
                "amount": 50.0,
                "currency": "EUR",
                "destination_iban": IBAN,
            }
        }
    )

    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("tb", "bankplat", "ext-b", "Bank", "", "text", "submitted", 50.0, "EUR", 50),
    )
    engine.db.execute(
        "INSERT INTO tasks(id, platform, external_id, title, description, category, status, reward_amount, reward_currency, priority, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        ("tc", "cryptoplat", "ext-c", "Crypto", "", "text", "submitted", 3.0, "USDC", 50),
    )

    class BankPlat:
        def check_payment(self, task_id):
            return {
                "method": "wise",
                "payment_status": "settled",
                "bank_reference": "SEPA-ENG-2",
                "amount": 50.0,
                "currency": "EUR",
                "provider_evidence": {"id": "should-ignore", "status": "completed", "amount": 50, "currency": "EUR", "destination_iban": IBAN},
            }

    class CryptoPlat:
        def check_payment(self, task_id):
            return {
                "payment_status": "settled",
                "payment_tx_hash": "0x" + "44" * 32,
                "to": WALLET,
                "amount": 3.0,
                "currency": "USDC",
                "network": "base",
            }

    engine.platforms = {"bankplat": BankPlat(), "cryptoplat": CryptoPlat()}

    receipt = {
        "status": "0x1",
        "blockNumber": "0x10",
        "logs": [
            {
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x" + "00" * 32,
                    "0x" + "00" * 12 + WALLET[2:],
                ],
                "data": hex(3_000_000),
            }
        ],
    }

    def fake_rpc(method, params, rpc_url):
        if method == "eth_getTransactionReceipt":
            return receipt
        if method == "eth_blockNumber":
            return "0x30"
        raise AssertionError(method)

    with patch("centbot.finance.payment_verify._rpc", side_effect=fake_rpc):
        updates = engine.reconcile_payments()
    methods = {u["method"] for u in updates}
    assert methods == {"bank", "crypto"}
    assert engine.ledger.bank_balance() > 0
    assert engine.ledger.crypto_balance() > 0
    # duplicates
    with patch("centbot.finance.payment_verify._rpc", side_effect=fake_rpc):
        assert engine.reconcile_payments() == []
    engine.shutdown()
