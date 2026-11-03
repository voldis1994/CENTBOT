"""ETH signing key helper — required for TaskMarket / BountyBook claims."""

from __future__ import annotations

from pathlib import Path

from eth_account import Account

from centbot.windows.eth_key import clear_private_key, set_private_key, signing_wallet_status


def test_set_and_status_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CENTBOT_ETH_PRIVATE_KEY", raising=False)
    acct = Account.create()
    result = set_private_key(acct.key.hex(), root=tmp_path)
    assert result["ok"] is True
    assert result["address"].lower() == acct.address.lower()
    st = signing_wallet_status(tmp_path)
    assert st["loaded"] is True
    assert st["address"].lower() == acct.address.lower()
    clear_private_key(root=tmp_path)
    st2 = signing_wallet_status(tmp_path)
    assert st2["loaded"] is False


def test_rejects_mnemonic(tmp_path: Path):
    phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    result = set_private_key(phrase, root=tmp_path)
    assert result["ok"] is False
    assert result["error"] == "seed_phrase_forbidden"
