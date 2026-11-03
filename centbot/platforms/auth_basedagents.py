"""BasedAgents AgentSig (Ed25519) identity and request signing."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import base58
from nacl.signing import SigningKey, VerifyKey

from centbot.platforms.http import HttpClient, PlatformHTTPError


@dataclass
class BasedAgentsIdentity:
    public_key_b58: str
    private_key_hex: str
    agent_id: str | None = None
    keypair_path: str | None = None

    @property
    def signing_key(self) -> SigningKey:
        return SigningKey(bytes.fromhex(self.private_key_hex))

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_key_b58": self.public_key_b58,
            "private_key_hex": self.private_key_hex,
            "agent_id": self.agent_id,
            "keypair_path": self.keypair_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BasedAgentsIdentity":
        return cls(
            public_key_b58=str(data["public_key_b58"]),
            private_key_hex=str(data["private_key_hex"]),
            agent_id=data.get("agent_id"),
            keypair_path=data.get("keypair_path"),
        )


def generate_identity() -> BasedAgentsIdentity:
    sk = SigningKey.generate()
    pk_b58 = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    return BasedAgentsIdentity(public_key_b58=pk_b58, private_key_hex=bytes(sk).hex())


def load_identity_file(path: Path) -> BasedAgentsIdentity | None:
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    # Support BasedAgents CLI keypair shape and CENTBOT shape
    if "private_key_hex" in data and "public_key_b58" in data:
        return BasedAgentsIdentity.from_dict(data)
    if "secretKey" in data or "privateKey" in data:
        # CLI often stores seed/secret as base64 or hex under varying keys
        secret = data.get("secretKey") or data.get("privateKey")
        if isinstance(secret, str) and len(secret) == 64:
            sk = SigningKey(bytes.fromhex(secret))
        elif isinstance(secret, str):
            import base64

            raw = base64.b64decode(secret)
            sk = SigningKey(raw[:32])
        else:
            return None
        pk_b58 = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
        return BasedAgentsIdentity(
            public_key_b58=pk_b58,
            private_key_hex=bytes(sk).hex(),
            agent_id=data.get("agent_id") or data.get("agentId"),
            keypair_path=str(path),
        )
    return None


def save_identity_file(identity: BasedAgentsIdentity, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(identity.to_dict(), indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def sign_headers(identity: BasedAgentsIdentity, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    # path without query
    clean_path = path.split("?", 1)[0]
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path
    message = f"{method.upper()}:{clean_path}:{ts}:{body_hash}:{nonce}".encode("utf-8")
    sig = identity.signing_key.sign(message).signature
    import base64

    sig_b64 = base64.b64encode(sig).decode("ascii")
    return {
        "Authorization": f"AgentSig {identity.public_key_b58}:{sig_b64}",
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-BasedAgents-Skill-Version": "centbot-1.0",
        "Content-Type": "application/json",
    }


def _pow_solve(challenge_b64: str, difficulty: int) -> str:
    """Find hex nonce such that sha256(challenge || nonce) has `difficulty` leading zero bits."""
    import base64

    challenge = base64.b64decode(challenge_b64)
    nonce = 0
    while True:
        nonce_hex = f"{nonce:08x}"
        digest = hashlib.sha256(challenge + nonce_hex.encode("ascii")).digest()
        # count leading zero bits
        bits = 0
        for b in digest:
            if b == 0:
                bits += 8
                continue
            bits += 8 - b.bit_length()
            break
        if bits >= difficulty:
            return nonce_hex
        nonce += 1


def register_agent(
    client: HttpClient,
    *,
    name: str,
    description: str,
    capabilities: list[str],
    identity: BasedAgentsIdentity | None = None,
) -> BasedAgentsIdentity:
    identity = identity or generate_identity()
    init = client.post_json("/v1/register/init", {"public_key": identity.public_key_b58})
    challenge_id = init["challenge_id"]
    challenge = init["challenge"]
    difficulty = int(init.get("difficulty", 18))
    nonce = _pow_solve(challenge, difficulty)
    # signature over utf8 challenge string as docs say: ed25519_sign(utf8_bytes(challenge))
    # The API doc says: signature: base64(ed25519_sign(utf8_bytes(challenge)))
    # where challenge is the base64-encoded challenge from init - typically sign the challenge bytes
    import base64

    challenge_bytes = base64.b64decode(challenge)
    # Docs: ed25519_sign(utf8_bytes(challenge)) — ambiguous; CLI signs challenge string.
    # Prefer signing the raw challenge bytes; fallback handled by API errors.
    sig = identity.signing_key.sign(challenge_bytes).signature
    sig_b64 = base64.b64encode(sig).decode("ascii")
    body = {
        "challenge_id": challenge_id,
        "public_key": identity.public_key_b58,
        "signature": sig_b64,
        "nonce": nonce,
        "profile": {
            "name": name,
            "description": description,
            "capabilities": capabilities,
            "protocols": ["https"],
            "version": "1.0.0",
        },
    }
    try:
        result = client.post_json("/v1/register/complete", body)
    except PlatformHTTPError as exc:
        # Retry signing utf-8 of base64 challenge string if raw bytes rejected
        if exc.status in (400, 401):
            sig2 = identity.signing_key.sign(challenge.encode("utf-8")).signature
            body["signature"] = base64.b64encode(sig2).decode("ascii")
            result = client.post_json("/v1/register/complete", body)
        else:
            raise
    identity.agent_id = result.get("agent_id") or result.get("id")
    return identity


def resolve_identity(config: dict[str, Any], credential_store_get=None) -> BasedAgentsIdentity | None:
    path = config.get("keypair_path") or os.environ.get("BASEDAGENTS_KEYPAIR_PATH")
    if path:
        ident = load_identity_file(Path(path))
        if ident:
            return ident
    if credential_store_get:
        data = credential_store_get("basedagents_identity")
        if isinstance(data, dict) and data.get("private_key_hex"):
            return BasedAgentsIdentity.from_dict(data)
    return None
