#!/usr/bin/env python3
"""Controlled live-platform trial: discover + local execute, never claim/submit/pay.

ALWAYS forces dry_run regardless of config ``mode: live``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from centbot.core.config import Config
from centbot.core.engine import CentBotEngine
from centbot.finance.payment_verify import CHAINS, confirm_payment
from centbot.sandbox.isolated import sandbox_available, sandbox_backend_info


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/cursor/artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Deliberately start from a live-looking config — controlled mode must override it.
    cfg = Config(
        overrides={
            "system": {"mode": "live", "max_parallel_tasks": 1},
            "analysis": {"auto_accept": True},
            "finance": {"reconcile_payments": True, "verify_on_chain": True},
            "platforms": {"bountybook": {"enabled": False}},
        }
    )
    engine = CentBotEngine(cfg)
    engine.enter_controlled_mode()
    evidence: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_mode_before_lock": "live",
        "mode": engine.config.get("system.mode"),
        "claims_allowed": False,
        "sandbox": sandbox_backend_info(),
        "sandbox_health": sandbox_available(),
        "supported_chains": sorted(CHAINS.keys()),
    }
    try:
        integrations = engine.integration_report()
        evidence["integrations"] = {
            k: {"ok": bool(v.get("ok")), "live": v.get("live"), "sample_task_count": v.get("sample_task_count")}
            for k, v in integrations.items()
        }
        trial = engine.run_live_trial(execute_local=True, controlled=True)
        evidence["mode"] = trial.get("mode")
        evidence["discovered"] = trial.get("discovered")
        evidence["eligible"] = trial.get("eligible")
        evidence["samples"] = trial.get("samples")
        executed = trial.get("executed") or []
        evidence["executed_count"] = len(executed)
        evidence["executed_ok"] = sum(1 for r in executed if r.get("ok"))
        evidence["payments_reconciled"] = trial.get("payments") or []
        evidence["verification"] = trial.get("verification")
        evidence["profit"] = trial.get("profit")
        evidence["payment_dispatcher_smoke"] = {
            "bank_platform_only_rejected": confirm_payment(
                {
                    "method": "bank",
                    "payment_status": "settled",
                    "bank_reference": "SEPA-TEST-0001",
                    "iban": "DE89370400440532013000",
                    "amount": 10,
                    "currency": "EUR",
                }
            ).get("reason"),
            "crypto_requires_recipient": confirm_payment(
                {"payment_status": "settled", "payment_tx_hash": "0x" + "ab" * 32, "network": "ethereum"},
                verify_chain=False,
            ).get("reason"),
        }
        evidence["verified"] = {
            "live_discovery": bool(evidence.get("discovered")),
            "integrations_ok": any(v.get("ok") for v in evidence["integrations"].values()),
            "sandbox_container": bool(evidence.get("sandbox_health")),
            "forced_dry_run": evidence.get("mode") == "dry_run",
            "full_claim_to_paid": False,
            "full_claim_to_paid_blocker": "controlled_dry_run_no_external_actions",
        }
        evidence["ok"] = bool(
            evidence["verified"]["live_discovery"]
            and evidence["verified"]["integrations_ok"]
            and evidence["verified"]["sandbox_container"]
            and evidence["verified"]["forced_dry_run"]
        )
    finally:
        engine.shutdown()
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()

    path = out_dir / "controlled-live-evidence.json"
    path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"evidence": str(path), "ok": evidence.get("ok"), "summary": evidence.get("verified")}, indent=2))
    return 0 if evidence.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
