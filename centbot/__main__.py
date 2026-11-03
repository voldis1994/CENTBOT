"""CLI entry: python -m centbot"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from centbot.core.config import Config
from centbot.core.engine import CentBotEngine


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CENTBOT autonomous workstation (live platforms)")
    p.add_argument("--config", default="config/default.yaml", help="Path to YAML config")
    p.add_argument("--once", action="store_true", help="Run a single live discovery/execute cycle and exit")
    p.add_argument(
        "--demo",
        action="store_true",
        help="Live feed trial: discover real tasks, optional local execute, no claims",
    )
    p.add_argument("--discover", action="store_true", help="Fetch and analyze live tasks only")
    p.add_argument("--status", action="store_true", help="Print status JSON and exit")
    p.add_argument("--integrations", action="store_true", help="Verify live platform integrations")
    p.add_argument("--mode", choices=["dry_run", "live"], help="Override system.mode")
    p.add_argument(
        "--register-basedagents",
        metavar="NAME",
        help="Generate/register a BasedAgents identity and save keypair",
    )
    p.add_argument(
        "--keypair",
        default="data/basedagents-keypair.json",
        help="Keypair path for --register-basedagents",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides: dict = {}
    if args.mode:
        overrides["system"] = {"mode": args.mode}
    config = Config(args.config, overrides=overrides or None)

    if args.register_basedagents:
        from centbot.platforms.auth_basedagents import generate_identity, register_agent, save_identity_file
        from centbot.platforms.http import HttpClient

        base = config.get("platforms.basedagents.base_url") or "https://api.basedagents.ai"
        client = HttpClient(str(base))
        identity = generate_identity()
        identity = register_agent(
            client,
            name=args.register_basedagents,
            description="CENTBOT autonomous worker",
            capabilities=["code", "data", "content", "research", "automation"],
            identity=identity,
        )
        path = Path(args.keypair)
        save_identity_file(identity, path)
        print(json.dumps({"ok": True, "agent_id": identity.agent_id, "keypair": str(path), "public_key": identity.public_key_b58}, indent=2))
        return 0

    engine = CentBotEngine(config)

    if args.status:
        print(json.dumps(engine.status(), indent=2, default=str))
        return 0
    if args.integrations:
        print(json.dumps(engine.integration_report(), indent=2, default=str))
        return 0
    if args.discover:
        analyzed = engine.discover_and_analyze()
        print(json.dumps({"discovered": len(analyzed), "eligible": sum(1 for t in analyzed if t.get("status") == "eligible"), "tasks": [
            {"platform": t["platform"], "title": t.get("title"), "reward": t.get("reward_amount"), "currency": t.get("reward_currency"), "status": t.get("status")}
            for t in analyzed[:30]
        ]}, indent=2, default=str))
        engine.shutdown()
        return 0
    if args.demo:
        report = engine.run_live_trial(execute_local=True)
        print(json.dumps(report, indent=2, default=str))
        engine.shutdown()
        return 0
    if args.once:
        summary = engine.cycle_once()
        print(json.dumps(summary, indent=2, default=str))
        engine.shutdown()
        return 0 if summary.get("ok") else 1

    engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
