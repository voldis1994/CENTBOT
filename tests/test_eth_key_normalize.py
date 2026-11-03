"""ETH key normalize + persist round-trip."""

from __future__ import annotations

from pathlib import Path

from eth_account import Account

from centbot.windows.eth_key import normalize_private_key, set_private_key, signing_wallet_status


def test_normalize_strips_quotes_and_spaces():
    raw = '  "0x' + ("ab" * 32) + '"  '
    out = normalize_private_key(raw)
    assert out.startswith("0x")
    assert len(out) == 66


def test_set_and_reload_via_eth_env(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    monkeypatch.delenv("CENTBOT_ETH_PRIVATE_KEY", raising=False)
    (tmp_path / "centbot").mkdir()
    (tmp_path / "START.bat").write_text("@echo off\n", encoding="utf-8")
    acct = Account.create()
    result = set_private_key(acct.key.hex(), root=tmp_path)
    assert result["ok"] is True
    assert (tmp_path / "data" / "eth.env").exists()
    monkeypatch.delenv("CENTBOT_ETH_PRIVATE_KEY", raising=False)
    st = signing_wallet_status(tmp_path)
    assert st["loaded"] is True
    assert st["address"].lower() == acct.address.lower()
