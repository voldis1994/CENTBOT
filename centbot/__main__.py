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
    p.add_argument("--once", action="store_true", help="Run a single discovery/execute cycle and exit")
    p.add_argument(
        "--demo",
        action="store_true",
        help="Controlled discovery trial (forces dry_run; no claims/submits/payments)",
    )
    p.add_argument(
        "--controlled-live",
        action="store_true",
        help="Explicit test harness: ALWAYS dry_run; blocks accept/submit/payment booking",
    )
    p.add_argument("--discover", action="store_true", help="Fetch and analyze live tasks only")
    p.add_argument("--status", action="store_true", help="Print status JSON and exit")
    p.add_argument("--live-status", action="store_true", help="Print live readiness blockers and exit")
    p.add_argument("--consistency", action="store_true", help="Audit config true/false mismatches and exit")
    p.add_argument("--ops-report", action="store_true", help="Write/print operations evidence report")
    p.add_argument("--integrations", action="store_true", help="Verify live platform integrations")
    p.add_argument(
        "--dashboard-only",
        action="store_true",
        help="Serve the control panel and exit on Ctrl+C (no work cycle)",
    )
    p.add_argument("--mode", choices=["dry_run", "live"], help="Override system.mode")
    p.add_argument(
        "--evidence-out",
        default="data/controlled-live-evidence.json",
        help="Evidence path for --controlled-live",
    )
    p.add_argument(
        "--ops-out",
        default="data/ops/operations-report.json",
        help="Path for --ops-report",
    )
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

    # ONLY --controlled-live / --demo may force dry_run over an intentional live config
    if args.controlled_live or args.demo:
        overrides = {
            **overrides,
            "system": {**(overrides.get("system") or {}), "mode": "dry_run"},
            "analysis": {"auto_accept": False},
            "finance": {"reconcile_payments": False},
        }

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
    if args.dashboard_only:
        from centbot.dashboard.app import create_dashboard, start_dashboard_thread

        host = str(config.get("dashboard.host", "127.0.0.1"))
        port = int(config.get("dashboard.port", 8787))
        # Bind all interfaces when host is localhost so cloud/browser testing can reach it
        bind = "0.0.0.0" if host in {"127.0.0.1", "localhost"} else host
        app = create_dashboard(
            engine.status,
            lambda: engine.emergency.trigger("dashboard"),
            ack_alert=engine.acknowledge_alert,
        )
        # Warm status/system snapshot once for first paint
        engine.monitor.snapshot()
        engine._last_snapshot = engine.monitor.snapshot().to_dict()
        start_dashboard_thread(app, bind, port)
        print(json.dumps({"ok": True, "dashboard": f"http://{bind}:{port}/", "mode": config.get("system.mode")}, indent=2))
        try:
            import time

            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            engine.shutdown()
            return 0
    if args.live_status:
        print(json.dumps(engine.live_readiness(), indent=2, default=str))
        engine.shutdown()
        return 0 if engine.live_readiness().get("ready") or not config.is_live() else 1
    if args.consistency:
        from centbot.core.consistency import audit_config

        report = audit_config(config)
        print(json.dumps(report, indent=2, default=str))
        engine.shutdown()
        return 0 if report.get("ok") else 1
    if args.ops_report:
        from centbot.quality.ops_report import write_operations_report

        report = engine.operations_report()
        out = write_operations_report(Path(args.ops_out), report)
        print(json.dumps({"evidence": str(out), "verified_success": report.get("verified_success"), "finances": report.get("finances")}, indent=2, default=str))
        engine.shutdown()
        return 0
    if args.integrations:
        print(json.dumps(engine.integration_report(), indent=2, default=str))
        return 0
    if args.discover:
        analyzed = engine.discover_and_analyze()
        print(json.dumps({"discovered": len(analyzed), "eligible": sum(1 for t in analyzed if t.get("status") == "eligible"), "mode": config.get("system.mode"), "tasks": [
            {"platform": t["platform"], "title": t.get("title"), "reward": t.get("reward_amount"), "currency": t.get("reward_currency"), "status": t.get("status")}
            for t in analyzed[:30]
        ]}, indent=2, default=str))
        engine.shutdown()
        return 0
    if args.demo or args.controlled_live:
        engine.enter_controlled_mode()
        report = engine.run_live_trial(execute_local=True, controlled=True)
        evidence = {
            "controlled": True,
            "mode": report.get("mode"),
            "claims_allowed": report.get("claims_allowed"),
            "acceptor_dry_run": report.get("acceptor_dry_run"),
            "submitter_dry_run": report.get("submitter_dry_run"),
            "sandbox": report.get("sandbox"),
            "integrations": {
                k: {"ok": bool(v.get("ok")), "sample_task_count": v.get("sample_task_count")}
                for k, v in (report.get("integrations") or {}).items()
            },
            "discovered": report.get("discovered"),
            "eligible": report.get("eligible"),
            "samples": report.get("samples"),
            "executed_ok": sum(1 for r in (report.get("executed") or []) if r.get("ok")),
            "verification": report.get("verification"),
            "payments": report.get("payments"),
        }
        out = Path(args.evidence_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"evidence": str(out), "verification": evidence.get("verification")}, indent=2, default=str))
        engine.shutdown()
        ok = bool((evidence.get("verification") or {}).get("live_discovery")) and evidence.get("mode") == "dry_run"
        return 0 if ok else 1
    if args.once:
        if config.is_live():
            readiness = engine.live_readiness()
            if not readiness.get("ready"):
                print(json.dumps({"ok": False, "reason": "live_not_ready", "readiness": readiness}, indent=2, default=str))
                engine.shutdown()
                return 2
        summary = engine.cycle_once()
        print(json.dumps(summary, indent=2, default=str))
        engine.shutdown()
        return 0 if summary.get("ok") else 1

    if config.is_live():
        readiness = engine.live_readiness()
        if not readiness.get("ready"):
            print(json.dumps({"ok": False, "reason": "live_not_ready", "readiness": readiness}, indent=2, default=str))
            engine.shutdown()
            return 2

    engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
