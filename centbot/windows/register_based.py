"""Register BasedAgents AgentSig identity into data/basedagents-keypair.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from centbot.runtime_paths import install_root


def _unique_agent_name(base: str, public_key_b58: str, *, attempt: int = 0) -> str:
    """Profile names are globally unique — bare 'CENTBOT' is often already taken (409)."""
    root = re.sub(r"[^A-Za-z0-9_-]", "", (base or "CENTBOT").strip())[:20] or "CENTBOT"
    suffix = public_key_b58[:8]
    if attempt <= 0:
        return f"{root}-{suffix}"
    extra = uuid.uuid4().hex[:6]
    return f"{root}-{suffix}-{extra}"


def _is_name_taken(exc: BaseException) -> bool:
    body = getattr(exc, "body", None)
    text = ""
    if isinstance(body, dict):
        text = str(body.get("message") or body.get("error") or "")
    text = f"{text} {exc}".lower()
    status = getattr(exc, "status", None)
    return status == 409 or "already taken" in text or "name" in text and "taken" in text


def register(*, name: str = "CENTBOT", root: Path | None = None) -> dict[str, Any]:
    from centbot.core.config import Config
    from centbot.platforms.auth_basedagents import (
        generate_identity,
        load_identity_file,
        register_agent,
        save_identity_file,
    )
    from centbot.platforms.http import HttpClient, PlatformHTTPError

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

    last_error: str | None = None
    last_body: Any = None
    used_name = ""
    for attempt in range(0, 4):
        used_name = _unique_agent_name(name or "CENTBOT", identity.public_key_b58, attempt=attempt)
        try:
            identity = register_agent(
                client,
                name=used_name,
                description="CENTBOT autonomous worker",
                capabilities=["code", "data", "content", "research", "automation"],
                identity=identity,
            )
            save_identity_file(identity, key_path)
            return {
                "ok": True,
                "agent_id": identity.agent_id,
                "name": used_name,
                "keypair": str(key_path),
                "public_key": identity.public_key_b58,
                "hint_lv": f"BasedAgents reģistrēts kā {used_name}. STOP.bat + START.bat.",
            }
        except PlatformHTTPError as exc:
            last_error = str(exc)
            last_body = exc.body
            if _is_name_taken(exc) and attempt < 3:
                continue
            break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            last_body = getattr(exc, "body", None)
            break

    return {
        "ok": False,
        "error": last_error or "register_failed",
        "body": last_body,
        "tried_name": used_name,
        "keypair": str(key_path),
        "hint_lv": "BasedAgents register neizdevās — pārbaudi tīklu; tad REGISTER_BASED.bat vēlreiz.",
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
