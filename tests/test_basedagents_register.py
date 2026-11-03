"""BasedAgents PoW registration — must match OpenAPI sha256(pubkey||utf8(challenge)||nonce_be32)."""

from __future__ import annotations

import base64
import hashlib

import base58
from nacl.signing import SigningKey

from centbot.platforms.auth_basedagents import (
    BasedAgentsIdentity,
    _leading_zero_bits,
    _pow_solve,
    generate_identity,
    register_agent,
)


def test_pow_matches_openapi_formula():
    sk = SigningKey.generate()
    pk_b58 = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    challenge = "AGXNT0JS3MODYtC65PGhXD4eWfxBBgzM4M4ZXCxH"
    difficulty = 12  # keep unit test fast
    nonce_hex = _pow_solve(pk_b58, challenge, difficulty)
    assert len(nonce_hex) == 8
    nonce = int(nonce_hex, 16)
    digest = hashlib.sha256(
        base58.b58decode(pk_b58) + challenge.encode("utf-8") + nonce.to_bytes(4, "big")
    ).digest()
    assert _leading_zero_bits(digest) >= difficulty


def test_pow_rejects_legacy_wrong_hash():
    """Old CENTBOT hashed base64-decoded challenge + ascii hex — must not match OpenAPI."""
    sk = SigningKey.generate()
    pk_b58 = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    # Use a challenge that looks like base64
    challenge = base64.b64encode(b"hello-basedagents-challenge!!").decode("ascii")
    difficulty = 10
    nonce_hex = _pow_solve(pk_b58, challenge, difficulty)
    nonce = int(nonce_hex, 16)
    legacy = hashlib.sha256(base64.b64decode(challenge) + nonce_hex.encode("ascii")).digest()
    correct = hashlib.sha256(
        base58.b58decode(pk_b58) + challenge.encode("utf-8") + nonce.to_bytes(4, "big")
    ).digest()
    assert _leading_zero_bits(correct) >= difficulty
    # Legacy hash is a different preimage — almost never satisfies the same difficulty bit check
    # on the *correct* formula; ensure our solver used the OpenAPI preimage.
    assert correct != legacy


def test_register_agent_live():
    """Live smoke: init+PoW+complete must return ag_… (network)."""
    from centbot.platforms.http import HttpClient

    client = HttpClient("https://api.basedagents.ai", timeout=90)
    identity = generate_identity()
    registered = register_agent(
        client,
        name="CENTBOT-TEST",
        description="CENTBOT registration unit probe",
        capabilities=["code", "data"],
        identity=identity,
    )
    assert registered.agent_id
    assert str(registered.agent_id).startswith("ag_")
