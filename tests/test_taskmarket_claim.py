"""TaskMarket claim signing + claimable filters (401/400/402 fixes)."""

from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

from centbot.platforms.auth_ethereum import (
    EthWallet,
    taskmarket_claim_message,
    taskmarket_read_message,
    taskmarket_submit_message,
)
from centbot.platforms.base import PlatformTask
from centbot.platforms.http import PlatformHTTPError
from centbot.platforms.taskmarket import (
    TaskMarketConnector,
    _claim_http_error,
    _hire_blocks_worker,
    _is_auto_claimable,
)


def test_claim_and_submit_messages_have_no_space():
    tid = "0x" + "ab" * 32
    assert taskmarket_claim_message(tid) == f"taskmarket:market:claim:{tid}"
    assert "claim: " not in taskmarket_claim_message(tid)
    assert taskmarket_submit_message(tid) == f"taskmarket:market:submit:{tid}"
    # Read auth keeps a space before the address
    assert taskmarket_read_message("0xAbc") == "taskmarket:read: 0xAbc"


def test_claim_signature_recovers_worker_address():
    acct = Account.create()
    wallet = EthWallet(private_key=acct.key.hex(), address=acct.address)
    tid = "0x" + "cd" * 32
    msg = taskmarket_claim_message(tid)
    sig = wallet.sign_message(msg)
    if not sig.startswith("0x"):
        sig = "0x" + sig
    recovered = Account.recover_message(encode_defunct(text=msg), signature=sig)
    assert to_checksum_address(recovered) == acct.address
    # Spaced message must NOT recover as the intended auth path for live API
    spaced = f"taskmarket:market:claim: {tid}"
    assert spaced != msg


def test_auto_claimable_filters_stake_bounty_hire():
    worker = "0x1111111111111111111111111111111111111111"
    other = "0x2222222222222222222222222222222222222222"
    base = {
        "id": "0x" + "11" * 32,
        "status": "open",
        "mode": "claim",
        "claimedBy": None,
        "stakeRequired": False,
        "hire": None,
    }
    assert _is_auto_claimable(base, worker) is True
    assert _is_auto_claimable({**base, "mode": "bounty"}, worker) is False
    assert _is_auto_claimable({**base, "stakeRequired": True}, worker) is False
    assert _is_auto_claimable({**base, "claimedBy": other}, worker) is False
    assert _is_auto_claimable({**base, "hire": {"worker": other, "kind": "reserved"}}, worker) is False
    assert _is_auto_claimable({**base, "hire": {"worker": worker, "kind": "reserved"}}, worker) is True
    assert _hire_blocks_worker({"hire": {"worker": other}}, worker) is True
    assert _hire_blocks_worker({"hire": {"worker": worker}}, worker) is False


def test_accept_task_skips_stake_and_bounty_without_http(monkeypatch):
    acct = Account.create()
    wallet = EthWallet(private_key=acct.key.hex(), address=acct.address)
    conn = TaskMarketConnector({"enabled": True, "min_reward": 0, "limit": 5}, wallet=wallet)

    def boom(*_a, **_k):
        raise AssertionError("HTTP should not be called for filtered accepts")

    monkeypatch.setattr(conn.client, "post_json", boom)

    bounty = PlatformTask(
        platform="taskmarket",
        external_id="0x" + "aa" * 32,
        title="bounty",
        raw={"source": "taskmarket", "task": {"mode": "bounty", "stakeRequired": False}},
    )
    r = conn.accept_task(bounty)
    assert r["ok"] is False
    assert r["error"] == "not_claim_mode"

    stake = PlatformTask(
        platform="taskmarket",
        external_id="0x" + "bb" * 32,
        title="stake",
        raw={"source": "taskmarket", "task": {"mode": "claim", "stakeRequired": True}},
    )
    r = conn.accept_task(stake)
    assert r["ok"] is False
    assert r["error"] == "stake_payment_required"

    hire = PlatformTask(
        platform="taskmarket",
        external_id="0x" + "cc" * 32,
        title="hire",
        raw={
            "source": "taskmarket",
            "task": {
                "mode": "claim",
                "stakeRequired": False,
                "hire": {"worker": "0x2222222222222222222222222222222222222222"},
            },
        },
    )
    r = conn.accept_task(hire)
    assert r["ok"] is False
    assert r["error"] == "hire_reserved"


def test_claim_http_error_mapping():
    e402 = PlatformHTTPError("pay", status=402, body={"error": "Payment required"})
    r = _claim_http_error(e402, "0x1")
    assert r["error"] == "stake_payment_required"

    e401 = PlatformHTTPError("sig", status=401, body={"error": "Signature does not match worker address"})
    r = _claim_http_error(e401, "0x1")
    assert r["error"] == "signature_mismatch"

    e400 = PlatformHTTPError("bad", status=400, body={"error": "Not a Claim task", "code": "BAD_REQUEST"})
    r = _claim_http_error(e400, "0x1")
    assert r["error"] == "not_claim_mode"

    e403 = PlatformHTTPError("hire", status=403, body={"error": "This task is a hire offered to another worker"})
    r = _claim_http_error(e403, "0x1")
    assert r["error"] == "hire_reserved"


def test_accept_posts_nospace_message_and_task_id(monkeypatch):
    acct = Account.create()
    wallet = EthWallet(private_key=acct.key.hex(), address=acct.address)
    conn = TaskMarketConnector({"enabled": True, "min_reward": 0}, wallet=wallet)
    tid = "0x" + "dd" * 32
    captured: dict = {}

    def fake_post(path, body, headers=None):
        captured["path"] = path
        captured["body"] = body
        captured["headers"] = headers
        return {"ok": True, "status": "claimed", "id": tid}

    monkeypatch.setattr(conn.client, "post_json", fake_post)
    task = PlatformTask(
        platform="taskmarket",
        external_id=tid,
        title="free",
        raw={"source": "taskmarket", "task": {"mode": "claim", "stakeRequired": False, "hire": None}},
    )
    result = conn.accept_task(task)
    assert result["ok"] is True
    assert captured["path"] == f"/api/tasks/{tid}/claim"
    assert captured["body"]["taskId"] == tid
    assert captured["body"]["workerAddress"] == acct.address
    assert captured["body"]["signature"].startswith("0x")
    assert result["signed_message"] == f"taskmarket:market:claim:{tid}"
    # Recover signer from posted signature
    recovered = Account.recover_message(
        encode_defunct(text=result["signed_message"]),
        signature=captured["body"]["signature"],
    )
    assert to_checksum_address(recovered) == acct.address
