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


def wallet_from_store(data: dict[str, Any] | str | None) -> EthWallet | None:
    if isinstance(data, str):
        data = {"private_key": data}
    if not data or not data.get("private_key"):
        return None
    key = str(data["private_key"]).strip()
    # Never treat a mnemonic / seed phrase as a signing key
    if " " in key and len(key.split()) >= 12:
        return None
    if not key.startswith("0x"):
        key = "0x" + key
    acct = Account.from_key(key)
    return EthWallet(private_key=key, address=acct.address)


def taskmarket_claim_message(task_id: str) -> str:
    # Live API + docs use no space after the final colon.
    # Spaced form always 401s: "Signature does not match worker address".
    return f"taskmarket:market:claim:{task_id}"


def taskmarket_submit_message(task_id: str) -> str:
    return f"taskmarket:market:submit:{task_id}"


def taskmarket_read_message(address: str) -> str:
    # Official CLI: taskmarket:read:{lowercaseAddress} (no space).
    return f"taskmarket:read:{str(address).lower()}"


def taskmarket_submit_message_with_keys(task_id: str, artifact_keys: list[str]) -> str:
    """Submit-from-keys binds artifactKey list: submit:{taskId}:{key1,key2}."""
    if not artifact_keys:
        return taskmarket_submit_message(task_id)
    return f"taskmarket:market:submit:{task_id}:{','.join(artifact_keys)}"
