"""CLI entry: python -m centbot"""

from __future__ import annotations

import argparse
import json
import sys

from centbot.core.config import Config
from centbot.core.engine import CentBotEngine


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CENTBOT autonomous workstation")
    p.add_argument("--config", default="config/default.yaml", help="Path to YAML config")
    p.add_argument(
        "--once",
        action="store_true",
        help="Run a single discovery/execute cycle and exit",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Run no-money-risk demo pipeline (discover, execute, account rewards)",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="Print status JSON and exit",
    )
    p.add_argument(
        "--integrations",
        action="store_true",
        help="Verify platform integrations and exit",
    )
    p.add_argument(
        "--mode",
        choices=["dry_run", "live"],
        help="Override system.mode",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {}
    if args.mode:
        overrides["system"] = {"mode": args.mode}
    config = Config(args.config, overrides=overrides or None)
    engine = CentBotEngine(config)

    if args.status:
        print(json.dumps(engine.status(), indent=2, default=str))
        return 0
    if args.integrations:
        print(json.dumps(engine.integration_report(), indent=2, default=str))
        return 0
    if args.demo:
        report = engine.run_demo_pipeline()
        print(json.dumps(report, indent=2, default=str))
        engine.shutdown()
        return 0 if report.get("eligible", 0) >= 0 else 1
    if args.once:
        summary = engine.cycle_once()
        print(json.dumps(summary, indent=2, default=str))
        engine.shutdown()
        return 0 if summary.get("ok") else 1

    engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
