"""BasedAgents registration must use unique profile names (bare CENTBOT → 409)."""

from __future__ import annotations

from centbot.windows.register_based import _is_name_taken, _unique_agent_name


def test_unique_agent_name_includes_pubkey_suffix():
    name = _unique_agent_name("CENTBOT", "AbCdEfGhXXXX")
    assert name == "CENTBOT-AbCdEfGh"
    assert name != "CENTBOT"
    retry = _unique_agent_name("CENTBOT", "AbCdEfGhXXXX", attempt=1)
    assert retry.startswith("CENTBOT-AbCdEfGh-")
    assert len(retry) > len(name)


def test_is_name_taken_detects_409():
    class Exc(Exception):
        status = 409
        body = {"error": "conflict", "message": "Agent name 'CENTBOT' is already taken"}

    assert _is_name_taken(Exc("POST -> 409")) is True

    class Other(Exception):
        status = 400
        body = {"message": "Invalid signature"}

    assert _is_name_taken(Other("bad")) is False
