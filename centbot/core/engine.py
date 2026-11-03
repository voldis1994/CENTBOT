"""Central CENTBOT control system and 24/7 work cycle."""

from __future__ import annotations

import json
import signal
import time
import traceback
from pathlib import Path
from typing import Any

from centbot.ai.analyzer import AITaskAnalyzer
from centbot.ai.decomposer import decompose
from centbot.ai.ollama_client import OllamaClient
from centbot.ai.planner import AIWorkPlanner
from centbot.ai.workers import WorkerCoordinator
from centbot.analysis.pipeline import AnalysisPipeline, AutoAcceptor
from centbot.android.emulator import EmulatorManager
from centbot.core.backup import BackupManager
from centbot.core.config import Config, ROOT
from centbot.core.database import Database, utcnow
from centbot.core.emergency import EmergencyStop
from centbot.core.logger import ActionJournal, get_logger, setup_logging
from centbot.core.monitor import SystemMonitor
from centbot.core.parallel import ParallelTaskSystem
from centbot.core.priority import sort_by_priority
from centbot.core.recovery import RecoveryManager
from centbot.dashboard.app import create_dashboard, start_dashboard_thread
from centbot.discovery.dedup import DuplicateFilter
from centbot.discovery.scanner import GlobalTaskScanner
from centbot.discovery.watcher import NewTaskWatcher
from centbot.executors.router import TaskExecutorRouter
from centbot.finance.currency import refresh_rates
from centbot.finance.ledger import FinanceLedger
from centbot.finance.optimization import ProfitOptimizer
from centbot.finance.payment_verify import confirm_payment
from centbot.finance.payments import PaymentIntegrations
from centbot.inputs.fetch import download_task_inputs
from centbot.platforms.registry import build_platforms, verify_integrations
from centbot.quality.error_fix import ErrorRepair
from centbot.quality.evidence import save_evidence
from centbot.quality.requirements import verify_against_requirements
from centbot.quality.result_check import verify_result
from centbot.sandbox.isolated import sandbox_available
from centbot.security.credentials import CredentialStore
from centbot.security.rate_limit import RateLimiter
from centbot.submission.rejection_fix import RejectionRepairProcess
from centbot.submission.status_check import SubmissionStatusChecker
from centbot.submission.submitter import Submitter

log = get_logger("centbot.engine")


class CentBotEngine:
    def __init__(self, config: Config):
        self.config = config
        self.root = ROOT
        log_dir = config.path_from("logging.directory", "logs")
        setup_logging(
            log_dir,
            level=str(config.get("logging.level", "INFO")),
            max_bytes=int(config.get("logging.max_bytes", 10_485_760)),
            backup_count=int(config.get("logging.backup_count", 10)),
        )
        self.journal = ActionJournal(log_dir)
        self.db = Database(config.path_from("database.path", "data/centbot.db"))
        self.emergency = EmergencyStop(config.path_from("system.emergency_stop_file", "data/EMERGENCY_STOP"), self.journal)
        self.monitor = SystemMonitor(
            cpu_warn=float(config.get("monitoring.cpu_warn_percent", 85)),
            ram_warn=float(config.get("monitoring.ram_warn_percent", 85)),
            gpu_warn=float(config.get("monitoring.gpu_warn_percent", 90)),
            internet_url=str(config.get("monitoring.internet_check_url", "https://1.1.1.1")),
        )
        self.recovery = RecoveryManager(
            self.journal,
            max_restarts=int(config.get("recovery.max_restarts", 5)),
            backoff=float(config.get("recovery.restart_backoff_seconds", 10)),
        )
        self.backup = BackupManager(
            config.path_from("database.path", "data/centbot.db"),
            config.path_from("backup.directory", "backups"),
            keep=int(config.get("backup.keep_count", 14)),
            journal=self.journal,
        )
        self.pool = ParallelTaskSystem(max_workers=int(config.get("system.max_parallel_tasks", 4)))
        self.credentials = CredentialStore(config.path_from("security.credentials_file", "data/credentials.enc"))
        self.platforms = build_platforms(config, credential_getter=self.credentials.get)
        self.scanner = GlobalTaskScanner(self.platforms, self.db, self.journal)
        self.dedup = DuplicateFilter(float(config.get("discovery.duplicate_similarity_threshold", 0.92)))
        self.watcher = NewTaskWatcher(self.db, self.journal)
        self.analysis = AnalysisPipeline(config.section("analysis"), self.journal)
        self.acceptor = AutoAcceptor(
            self.platforms,
            config.section("analysis"),
            self.journal,
            dry_run=config.is_dry_run(),
        )
        self.executor = TaskExecutorRouter(
            browser_enabled=bool(config.get("browser.enabled", True)),
            android_enabled=bool(config.get("android.enabled", False)),
            headless=bool(config.get("browser.headless", True)),
            timeout_ms=int(config.get("browser.timeout_ms", 30000)),
            user_agent=str(config.get("browser.user_agent") or None),
            adb_path=str(config.get("android.adb_path", "adb")),
            emulator_path=str(config.get("android.emulator_path", "emulator")),
        )
        self.repair = ErrorRepair(max_attempts=2)
        if not sandbox_available():
            self.db.add_alert("critical", "centbot.sandbox.isolated unavailable", source="sandbox")
            self.journal.record("sandbox", "error", available=False)
        else:
            self.journal.record("sandbox", "ok", available=True)
        try:
            refresh_rates(force=True)
        except Exception as exc:  # noqa: BLE001
            self.journal.record("fx", "error", error=str(exc))
        self.submitter = Submitter(self.platforms, self.db, self.journal, dry_run=config.is_dry_run())
        self.status_checker = SubmissionStatusChecker(self.platforms, self.db)
        self.rejection_repair = RejectionRepairProcess(self.db, self.journal)
        self.ledger = FinanceLedger(
            self.db,
            self.journal,
            default_currency=str(config.get("finance.default_currency", "USD")),
            wallet_public=str(config.get("finance.crypto_wallet_public", "")),
        )
        self.payments = PaymentIntegrations(str(config.get("finance.crypto_wallet_public", "")))
        self.optimizer = ProfitOptimizer(self.db, self.ledger, self.journal, config.section("finance"))
        self.rate_limiter = RateLimiter(int(config.get("security.rate_limit_per_minute", 30)))
        self.ollama = OllamaClient(
            base_url=str(config.get("ai.ollama_base_url", "http://127.0.0.1:11434")),
            model=str(config.get("ai.model", "tinyllama")),
            timeout=float(config.get("ai.timeout_seconds", 60)),
        )
        self.ai_analyzer = AITaskAnalyzer(self.ollama, enabled=bool(config.get("ai.enabled", False)))
        self.planner = AIWorkPlanner(self.ai_analyzer)
        self.workers = WorkerCoordinator()
        self.emulator = EmulatorManager(
            emulator_path=str(config.get("android.emulator_path", "emulator")),
            adb_path=str(config.get("android.adb_path", "adb")),
            max_emulators=int(config.get("android.max_emulators", 2)),
            default_avd=str(config.get("android.default_avd", "CentBot_API_30")),
        )
        self._running = False
        self._cycles = 0
        self._last_snapshot: dict[str, Any] = {}
        self._register_default_workers()
        self._ensure_platform_stats()

    def _register_default_workers(self) -> None:
        self.workers.register("system", lambda ctx: {"ok": True})
        self.workers.register("quality", lambda ctx: {"ok": True})
        self.workers.register("testing", lambda ctx: {"ok": True})
        for cat in ("csv", "excel", "json_xml", "pdf", "image", "text", "programming", "browser", "android", "other"):
            self.workers.register(cat, lambda ctx, c=cat: {"ok": True, "worker": c})

    def _ensure_platform_stats(self) -> None:
        for name in self.platforms:
            if not self.db.fetchone("SELECT platform FROM platform_stats WHERE platform=?", (name,)):
                self.db.execute(
                    "INSERT INTO platform_stats(platform, enabled, updated_at) VALUES(?,?,?)",
                    (name, 1, utcnow()),
                )

    def integration_report(self) -> dict[str, Any]:
        return verify_integrations(self.platforms)

    def status(self) -> dict[str, Any]:
        counts = {
            r["status"]: r["c"]
            for r in self.db.fetchall("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status")
        }
        alerts = self.db.fetchall(
            "SELECT level, message, created_at FROM alerts WHERE acknowledged=0 ORDER BY id DESC LIMIT 10"
        )
        recent = self.db.fetchall(
            "SELECT title, platform, status, expected_profit FROM tasks ORDER BY updated_at DESC LIMIT 12"
        )
        return {
            "mode": self.config.get("system.mode"),
            "cycles": self._cycles,
            "running": self._running,
            "emergency": self.emergency.is_active(),
            "workers": {"active": self.pool.active_count(), "ids": self.pool.active_ids()},
            "tasks": {
                "total": sum(counts.values()),
                "eligible": counts.get("eligible", 0) + counts.get("accepted", 0),
                "running": counts.get("running", 0),
                "completed": counts.get("completed", 0),
                "rejected": counts.get("rejected", 0),
                "by_status": counts,
            },
            "finance": {
                "profit": self.ledger.total_profit(),
                "currency": self.config.get("finance.default_currency", "USD"),
                "wallet_public_set": bool(self.config.get("finance.crypto_wallet_public")),
            },
            "system": self._last_snapshot,
            "alerts": alerts,
            "recent_tasks": recent,
            "android": self.emulator.status(),
            "ai": {"enabled": bool(self.config.get("ai.enabled")), "ollama": self.ollama.available()},
            "integrations": {k: v.get("ok") for k, v in self.integration_report().items()},
        }

    def discover_and_analyze(self) -> list[dict[str, Any]]:
        if not self.rate_limiter.allow():
            self.journal.record("discover", "rate_limited")
            return []
        raw = self.scanner.scan()
        known = {r["fingerprint"] for r in self.db.fetchall("SELECT fingerprint FROM tasks WHERE fingerprint IS NOT NULL")}
        unique = self.dedup.filter(raw, known)
        new_tasks = self.watcher.detect_new(unique)
        analyzed = []
        for row in new_tasks:
            item = self.analysis.analyze(row)
            # Persist without non-serializable bits
            store = {k: v for k, v in item.items() if k not in ("_task", "is_new", "reject_reason", "automation_allowed")}
            if item.get("reject_reason"):
                store_raw = store.get("raw_json") or {}
                if isinstance(store_raw, str):
                    try:
                        store_raw = json.loads(store_raw)
                    except json.JSONDecodeError:
                        store_raw = {"raw": store_raw}
                store_raw = dict(store_raw)
                store_raw["reject_reason"] = item["reject_reason"]
                store["raw_json"] = store_raw
            self.db.upsert_task(store)
            analyzed.append(item)
            if item["status"] == "rejected":
                self.ledger.update_platform_stats(item["platform"], rejected=1)
        return analyzed

    def _work_dir(self, task_id: str) -> Path:
        path = self.root / "sandbox" / "tasks" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def execute_task(self, task_row: dict[str, Any]) -> dict[str, Any]:
        task_id = task_row["id"]
        self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("running", utcnow(), task_id))
        self.db.execute(
            "INSERT INTO task_runs(task_id, worker, status, started_at) VALUES(?,?,?,?)",
            (task_id, task_row.get("category") or "general", "running", utcnow()),
        )
        workdir = self._work_dir(task_id)
        inputs = download_task_inputs(task_row, workdir)
        self.journal.record("inputs", "ok" if inputs.get("ok") else "partial", task_id=task_id, **{k: inputs.get(k) for k in ("saved", "errors", "urls")})
        plan = self.planner.plan(task_row)
        subtasks = decompose(task_row)
        self.workers.run_subtasks(subtasks, {"task": task_row, "plan": plan})

        def _run() -> dict[str, Any]:
            result = self.executor.execute(task_row, workdir)
            check = verify_result(result.to_dict(), workdir)
            req = verify_against_requirements(task_row, result.to_dict(), workdir)
            ok_local = bool(result.ok and check["ok"] and req["ok"])
            return {
                "ok": ok_local,
                "result": result.to_dict(),
                "check": check,
                "requirements": req,
                "error": None if ok_local else (result.error or check.get("issues") or req.get("issues")),
            }

        outcome = self.repair.run_with_repair(_run)
        evidence = save_evidence(task_id, workdir, self.root / "data" / "evidence", {"outcome": outcome, "plan": plan, "inputs": inputs})
        ok = bool(outcome.get("ok"))
        status = "completed" if ok else "failed"
        self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, utcnow(), task_id))
        self.db.execute(
            "UPDATE task_runs SET status=?, finished_at=?, evidence_path=?, error=? WHERE id=("
            "SELECT id FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1)",
            (status, utcnow(), str(evidence), None if ok else str(outcome.get("error") or outcome.get("check")), task_id),
        )
        if ok:
            self.ledger.update_platform_stats(task_row["platform"], completed=1)
            from centbot.platforms.hydrate import task_from_row

            submit_payload = {
                "summary": f"CENTBOT completed {task_row.get('title')}",
                "evidence": str(evidence),
                "output": outcome.get("result", {}).get("output"),
                "content": outcome.get("result", {}).get("output"),
            }
            task_obj = task_row.get("_task") or task_from_row(task_row)
            submit_row = {**task_row, "_task": task_obj}
            submit_result = self.submitter.submit(submit_row, submit_payload)
            if submit_result.get("ok") and not self.config.is_dry_run():
                self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("submitted", utcnow(), task_id))
            self.journal.record("submit_result", "ok" if submit_result.get("ok") else "pending", task_id=task_id, result=submit_result)
        else:
            self.optimizer.learn_from_reward(task_row["platform"], False)
            self.rejection_repair.handle(task_id, reason=str(outcome.get("error") or "failed"))
        self.journal.record("execute", status, task_id=task_id, evidence=str(evidence))
        return {"ok": ok, "task_id": task_id, "evidence": str(evidence), "inputs": inputs}

    def schedule_eligible(self) -> int:
        from centbot.platforms.hydrate import task_from_row

        rows = self.db.fetchall("SELECT * FROM tasks WHERE status IN ('eligible','accepted','needs_repair') ORDER BY priority DESC")
        launched = 0
        for row in sort_by_priority(rows):
            if not self.pool.has_capacity():
                break
            if self.emergency.is_active():
                break
            task_obj = task_from_row(row)
            row = {**row, "_task": task_obj}
            if row["status"] == "eligible":
                if self.config.is_dry_run():
                    # Local practice run: mark accepted without calling platform claim APIs
                    self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("accepted", utcnow(), row["id"]))
                    row["status"] = "accepted"
                else:
                    accept = self.acceptor.accept({**row, "status": "eligible", "_task": task_obj})
                    if not accept.get("ok"):
                        self.journal.record("accept", "skipped", task_id=row["id"], result=accept)
                        continue
                    self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("accepted", utcnow(), row["id"]))
                    self.ledger.update_platform_stats(row["platform"], accepted=1)
                    row["status"] = "accepted"
            self.pool.submit(row["id"], int(row.get("priority") or 50), self.execute_task, row)
            launched += 1
        return launched

    def reconcile_payments(self) -> list[dict[str, Any]]:
        """Book income only after platform status is settled and a real tx is present."""
        if not self.config.get("finance.reconcile_payments", True):
            return []
        require_tx = bool(self.config.get("finance.require_tx_hash", True))
        updates: list[dict[str, Any]] = []
        pending = self.db.fetchall(
            "SELECT * FROM tasks WHERE status IN ('completed','submitted','verified') ORDER BY updated_at DESC LIMIT 40"
        )
        for row in pending:
            conn = self.platforms.get(row["platform"])
            if not conn or not hasattr(conn, "check_payment"):
                continue
            try:
                pay = conn.check_payment(row["external_id"])
            except Exception as exc:  # noqa: BLE001
                self.journal.record("payment_check", "error", task_id=row["id"], error=str(exc))
                continue
            wallet = str(self.config.get("finance.crypto_wallet_public") or "").strip() or None
            if not wallet:
                self.journal.record("payment_check", "pending", task_id=row["id"], reason="recipient_required")
                continue
            confirmed = confirm_payment(
                pay if isinstance(pay, dict) else None,
                require_tx=require_tx,
                expected_wallet=wallet,
                expected_amount=float(row.get("reward_amount") or 0) or None,
                min_confirmations=int(self.config.get("finance.min_confirmations", 1)),
                verify_chain=bool(self.config.get("finance.verify_on_chain", True)),
            )
            if not confirmed.get("ok"):
                self.journal.record(
                    "payment_check",
                    "pending",
                    task_id=row["id"],
                    reason=confirmed.get("reason"),
                    payment_status=confirmed.get("status"),
                    tx_hash=confirmed.get("tx_hash"),
                    confirmations=confirmed.get("confirmations"),
                )
                continue
            amount = float(confirmed.get("amount") or row.get("reward_amount") or 0)
            # Prefer on-chain matched transfer amount when present
            transfer = confirmed.get("transfer") if isinstance(confirmed.get("transfer"), dict) else None
            if transfer and transfer.get("amount") is not None:
                amount = float(transfer["amount"])
            currency = str((transfer or {}).get("token") or confirmed.get("currency") or row.get("reward_currency") or "USDC")
            tx_ref = str(confirmed.get("tx_hash"))
            recorded = self.ledger.record_crypto_reward(
                amount=amount,
                currency=currency,
                platform=row["platform"],
                task_id=row["id"],
                tx_ref=tx_ref,
            )
            if recorded:
                self.optimizer.learn_from_reward(row["platform"], True, amount_base=amount)
                self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("paid", utcnow(), row["id"]))
                updates.append({"task_id": row["id"], "tx_ref": tx_ref, "amount": amount, "currency": currency})
                self.journal.record("payment_received", "ok", task_id=row["id"], tx_ref=tx_ref, amount=amount)
            else:
                self.journal.record("payment_received", "duplicate", task_id=row["id"], tx_ref=tx_ref)
        return updates

    def cycle_once(self) -> dict[str, Any]:
        if self.emergency.is_active():
            return {"ok": False, "reason": "emergency_stop"}
        snap = self.monitor.snapshot()
        self._last_snapshot = snap.to_dict()
        self.db.set_state("system_snapshot", self._last_snapshot)
        for msg in self.monitor.warnings(snap):
            self.db.add_alert("warning", msg, source="monitor")
            self.journal.record("monitor_warning", "warn", message=msg)

        analyzed = self.discover_and_analyze()
        launched = self.schedule_eligible()
        submission_updates = self.status_checker.poll_pending()
        payments = self.reconcile_payments()
        if self.config.get("backup.enabled", True):
            self.backup.maybe_backup(float(self.config.get("backup.interval_hours", 6)))
        if self.config.get("profit_optimization.enabled", True) and self._cycles % int(self.config.get("profit_optimization.rebalance_every_cycles", 20) or 20) == 0:
            self.optimizer.rebalance_priorities()
            self.optimizer.stop_unprofitable()

        self._cycles += 1
        self.db.set_state("cycles", self._cycles)
        summary = {
            "ok": True,
            "cycle": self._cycles,
            "analyzed": len(analyzed),
            "launched": launched,
            "submissions": len(submission_updates),
            "payments": len(payments),
            "profit": self.ledger.total_profit(),
            "active_workers": self.pool.active_count(),
            "mode": self.config.get("system.mode"),
        }
        self.journal.record("cycle", "ok", **summary)
        return summary

    def run_forever(self) -> None:
        self._running = True
        pid_path = self.config.path_from("system.pid_file", "data/centbot.pid")
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(__import__("os").getpid()), encoding="utf-8")

        if self.config.get("dashboard.enabled", True):
            app = create_dashboard(self.status, lambda: self.emergency.trigger("dashboard"))
            start_dashboard_thread(app, str(self.config.get("dashboard.host", "127.0.0.1")), int(self.config.get("dashboard.port", 8787)))
            log.info("Dashboard on http://%s:%s", self.config.get("dashboard.host"), self.config.get("dashboard.port"))

        self.journal.record("start", "ok", mode=self.config.get("system.mode"), integrations=self.integration_report())
        interval = float(self.config.get("system.cycle_interval_seconds", 30))

        def _handle_sig(_signum: int, _frame: Any) -> None:
            log.info("Signal received, shutting down…")
            self.stop()

        signal.signal(signal.SIGINT, _handle_sig)
        signal.signal(signal.SIGTERM, _handle_sig)

        try:
            while self._running and not self.emergency.is_active():
                ok = self.recovery.run_protected("cycle", lambda: self.cycle_once())
                if not ok or self.recovery.should_halt():
                    self.emergency.trigger("recovery_halt")
                    break
                time.sleep(interval)
        finally:
            self.shutdown()

    def run_demo_pipeline(self) -> dict[str, Any]:
        """Live discovery trial: fetch real gigs, analyze, optionally execute locally without claims."""
        return self.run_live_trial(execute_local=True)

    def run_live_trial(self, *, execute_local: bool = True) -> dict[str, Any]:
        """Pull real platform feeds, analyze, and (optionally) practice-execute without claiming."""
        report: dict[str, Any] = {"integrations": self.integration_report(), "mode": self.config.get("system.mode")}
        analyzed = self.discover_and_analyze()
        report["discovered"] = len(analyzed)
        eligible = [t for t in analyzed if t.get("status") == "eligible"]
        report["eligible"] = len(eligible)
        report["samples"] = [
            {"platform": t["platform"], "title": (t.get("title") or "")[:80], "reward": t.get("reward_amount"), "currency": t.get("reward_currency")}
            for t in sort_by_priority(eligible)[:10]
        ]
        results = []
        if execute_local:
            for row in sort_by_priority(eligible)[: int(self.config.get("system.max_parallel_tasks", 4))]:
                self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("accepted", utcnow(), row["id"]))
                results.append(self.execute_task(row))
        report["executed"] = results
        report["payments"] = self.reconcile_payments()
        report["profit"] = self.ledger.total_profit()
        report["income"] = self.ledger.income_history(20)
        report["platform_stats"] = self.ledger.platform_profitability()
        self.journal.record(
            "live_trial",
            "ok",
            discovered=report["discovered"],
            eligible=report["eligible"],
            executed=len(results),
        )
        return report

    def stop(self) -> None:
        self._running = False

    def shutdown(self) -> None:
        self._running = False
        self.pool.shutdown(wait=False)
        self.emulator.stop_all()
        pid_path = self.config.path_from("system.pid_file", "data/centbot.pid")
        if pid_path.exists():
            pid_path.unlink(missing_ok=True)
        try:
            self.backup.backup_now()
        except Exception:  # noqa: BLE001
            log.error("Final backup failed:\n%s", traceback.format_exc())
        self.journal.record("shutdown", "ok", cycles=self._cycles)
