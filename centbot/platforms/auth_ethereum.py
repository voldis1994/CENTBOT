"""Ethereum EIP-191 signing helpers for TaskMarket / BountyBook style APIs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct


@dataclass
class EthWallet:
    private_key: str
    address: str

    def sign_message(self, message: str) -> str:
        signed = Account.sign_message(encode_defunct(text=message), private_key=self.private_key)
        return signed.signature.hex()
        # eth_account returns 0x-prefixed hex via HexBytes

    def to_public(self) -> dict[str, str]:
        return {"address": self.address}


def wallet_from_env(env_name: str = "CENTBOT_ETH_PRIVATE_KEY") -> EthWallet | None:
    key = os.environ.get(env_name, "").strip()
    if not key:
        return None
    if not key.startswith("0x"):
        key = "0x" + key
    acct = Account.from_key(key)
    return EthWallet(private_key=key, address=acct.address)


def wallet_from_store(data: dict[str, Any] | None) -> EthWallet | None:
    if not data or not data.get("private_key"):
        return None
    key = str(data["private_key"])
    if not key.startswith("0x"):
        key = "0x" + key
    acct = Account.from_key(key)
    return EthWallet(private_key=key, address=acct.address)


def taskmarket_claim_message(task_id: str) -> str:
    return f"taskmarket:market:claim: {task_id}"


def taskmarket_submit_message(task_id: str) -> str:
    return f"taskmarket:market:submit: {task_id}"


def taskmarket_read_message(address: str) -> str:
    return f"taskmarket:read: {address}"
