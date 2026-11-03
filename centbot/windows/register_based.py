"""Register BasedAgents AgentSig identity into data/basedagents-keypair.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from centbot.runtime_paths import install_root


def register(*, name: str = "CENTBOT", root: Path | None = None) -> dict[str, Any]:
    from centbot.core.config import Config
    from centbot.platforms.auth_basedagents import (
        generate_identity,
        load_identity_file,
        register_agent,
        save_identity_file,
    )
    from centbot.platforms.http import HttpClient

    base_root = Path(root) if root else install_root()
    config = Config()
    key_rel = str(config.get("platforms.basedagents.keypair_path") or "data/basedagents-keypair.json")
    key_path = Path(key_rel) if Path(key_rel).is_absolute() else base_root / key_rel
    existing = load_identity_file(key_path)
    if existing and existing.agent_id:
        return {
            "ok": True,
            "skipped": True,
            "agent_id": existing.agent_id,
            "keypair": str(key_path),
            "hint_lv": "BasedAgents identity jau ir — claim iespējams.",
        }
    base = str(config.get("platforms.basedagents.base_url") or "https://api.basedagents.ai")
    # PoW difficulty can be ~22 — allow enough time for solve + complete
    client = HttpClient(base.rstrip("/"), timeout=120)
    identity = existing or generate_identity()
    # Persist keypair before network complete so a mid-flight crash still has keys
    if not existing:
        save_identity_file(identity, key_path)
    try:
        identity = register_agent(
            client,
            name=name or "CENTBOT",
            description="CENTBOT autonomous worker",
            capabilities=["code", "data", "content", "research", "automation"],
            identity=identity,
        )
    except Exception as exc:  # noqa: BLE001
        body = getattr(exc, "body", None)
        return {
            "ok": False,
            "error": str(exc),
            "body": body,
            "keypair": str(key_path),
            "hint_lv": "BasedAgents register/complete neizdevās — pārbaudi tīklu un palaid REGISTER_BASED.bat.",
        }
    save_identity_file(identity, key_path)
    return {
        "ok": True,
        "agent_id": identity.agent_id,
        "keypair": str(key_path),
        "public_key": identity.public_key_b58,
        "hint_lv": "BasedAgents reģistrēts. STOP.bat + START.bat.",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Register BasedAgents identity")
    p.add_argument("--name", default="CENTBOT")
    args = p.parse_args(argv)
    try:
        result = register(name=args.name)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
