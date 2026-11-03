"""BasedAgents identity resolve + default keypair path."""

from __future__ import annotations

from pathlib import Path

from centbot.platforms.auth_basedagents import generate_identity, resolve_identity, save_identity_file


def test_resolve_identity_default_install_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("centbot.runtime_paths.install_root", lambda: tmp_path)
    key = tmp_path / "data" / "basedagents-keypair.json"
    identity = generate_identity()
    identity.agent_id = "agent-test"
    save_identity_file(identity, key)
    found = resolve_identity({})
    assert found is not None
    assert found.agent_id == "agent-test"
    assert found.public_key_b58 == identity.public_key_b58
