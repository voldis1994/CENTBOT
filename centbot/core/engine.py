"""Central CENTBOT control system and 24/7 work cycle."""

from __future__ import annotations

import json
import os
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
from centbot.core.config import Config
from centbot.runtime_paths import install_root
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
from centbot.finance.bank_providers import HttpBankProvider
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
        self.root = install_root()
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
        try:
            from centbot.windows.android_sdk import ensure_path_env, resolve_sdk_tools

            _sdk_early = ensure_path_env(resolve_sdk_tools())
        except Exception:  # noqa: BLE001
            _sdk_early = {}
        self.executor = TaskExecutorRouter(
            browser_enabled=bool(config.get("browser.enabled", True)),
            android_enabled=bool(config.get("android.enabled", True)),
            headless=bool(config.get("browser.headless", True)),
            timeout_ms=int(config.get("browser.timeout_ms", 30000)),
            user_agent=str(config.get("browser.user_agent") or None),
            adb_path=str(config.get("android.adb_path") or _sdk_early.get("adb") or "adb"),
            emulator_path=str(config.get("android.emulator_path") or _sdk_early.get("emulator") or "emulator"),
        )
        self.repair = ErrorRepair(max_attempts=2)
        # Sandbox must NEVER block engine start. Docker OK → container; else restrictor.
        try:
            from centbot.sandbox.isolated import sandbox_diagnose

            sand = sandbox_diagnose()
        except Exception as sand_exc:  # noqa: BLE001
            sand = {"ok": False, "error": str(sand_exc), "hint_lv": "sandbox_diagnose_failed"}
        if sand.get("ok"):
            self.journal.record("sandbox", "ok", available=True, backend=sand.get("selected"))
            os.environ["CENTBOT_REQUIRE_CONTAINER"] = "1"
        else:
            # Critical: force soft fallback so TaskMarket/BasedAgents keep running
            os.environ["CENTBOT_REQUIRE_CONTAINER"] = "0"
            msg = (
                "sandbox: Docker nav gatavs — PC lane lieto restrictor (LIVE turpinās). "
                "Kad Docker Engine Running: ENSURE_DOCKER.bat"
            )
            if sand.get("docker_on_path"):
                msg = (
                    "sandbox: Docker ir PATH, bet image/Engine nav OK — lietoju restrictor. "
                    "ENSURE_DOCKER.bat (pull python:3.12-slim), tad STOP+START"
                )
            existing = self.db.fetchone(
                "SELECT id FROM alerts WHERE acknowledged=0 AND source=? LIMIT 1",
                ("sandbox",),
            )
            if not existing:
                self.db.add_alert("info", msg, source="sandbox")
            self.journal.record(
                "sandbox",
                "warn",
                available=False,
                fallback="restrictor",
                docker_on_path=sand.get("docker_on_path"),
                error=sand.get("error"),
            )
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
        avds = config.get("android.avds") or [
            "CENTBOT_ANDROID_01",
            "CENTBOT_ANDROID_02",
            "CENTBOT_ANDROID_03",
            "CENTBOT_ANDROID_04",
        ]
        if not isinstance(avds, list):
            avds = ["CENTBOT_ANDROID_01", "CENTBOT_ANDROID_02", "CENTBOT_ANDROID_03", "CENTBOT_ANDROID_04"]
        android_enabled = bool(config.get("android.enabled", True))
        android_slots = int(config.get("android.max_emulators", 4) or 4) if android_enabled else 0
        _emu_bin = str(config.get("android.emulator_path") or _sdk_early.get("emulator") or "emulator")
        _adb_bin = str(config.get("android.adb_path") or _sdk_early.get("adb") or "adb")
        self.emulator = EmulatorManager(
            emulator_path=_emu_bin,
            adb_path=_adb_bin,
            max_emulators=int(config.get("android.max_emulators", 4) or 4),
            default_avd=str(config.get("android.default_avd", "CENTBOT_ANDROID_01")),
            avds=[str(x) for x in avds],
            enabled=android_enabled,
        )
        from centbot.workers.distributor import SmartWorkDistributor

        self.distributor = SmartWorkDistributor(
            max_pc=int(config.get("system.max_parallel_tasks", 6) or 6),
            android_slots=android_slots,
        )
        self._running = False
        self._cycles = 0
        self._last_snapshot: dict[str, Any] = {}
        self._controlled_mode = False
        self._bank_provider = None
        self._integrations_cache: dict[str, Any] | None = None
        self._integrations_cache_at = 0.0
        bank_base = str(self.config.get("finance.bank_provider_base_url") or "")
        bank_key_env = str(self.config.get("finance.bank_provider_api_key_env") or "")
        bank_key = self.config.env(bank_key_env) if bank_key_env else ""
        if bank_base:
            self._bank_provider = HttpBankProvider(bank_base, api_key=bank_key)
        self._register_default_workers()
        self._ensure_platform_stats()
        # Refuse simulated rewards in any mode — income must be independently verified
        if bool(self.config.get("finance.simulate_rewards_in_dry_run", False)):
            self.config.set("finance.simulate_rewards_in_dry_run", False)
            self.journal.record("config", "sanitized", field="simulate_rewards_in_dry_run", value=False)
            self.db.add_alert("warning", "simulate_rewards_in_dry_run forced off — no synthetic income", source="finance")
        # Live: ensure BasedAgents keypair exists so claims are not identity_missing spam
        if self.config.is_live() and not self._controlled_mode:
            try:
                self._ensure_basedagents_identity()
            except Exception as exc:  # noqa: BLE001
                self.journal.record("basedagents_register", "error", error=str(exc))

    def enter_controlled_mode(self) -> None:
        """Force dry_run and block all real accept/submit/payment booking side effects.

        Only for explicit ``--controlled-live`` / test harnesses — never used by
        normal ``run_forever`` / ``--once`` when the user chose live mode.
        """
        self.config.force_dry_run()
        self.config.set("analysis.auto_accept", False)
        self.config.set("finance.reconcile_payments", False)
        self.acceptor.dry_run = True
        self.submitter.dry_run = True
        self._controlled_mode = True
        self.journal.record("controlled_mode", "enabled", mode="dry_run", claims_allowed=False)

    def live_readiness(self, integrations: dict[str, Any] | None = None) -> dict[str, Any]:
        """Honest gate: what is missing before real claims/submits/payments can succeed."""
        from centbot.core.consistency import audit_config

        live = self.config.is_live()
        blockers: list[str] = []
        if not live:
            blockers.append("system.mode_not_live")
        if not bool(self.config.get("analysis.auto_accept", False)):
            blockers.append("analysis.auto_accept_disabled")
        if self._controlled_mode:
            blockers.append("controlled_mode_active")
        if self.acceptor.dry_run or self.submitter.dry_run:
            blockers.append("acceptor_or_submitter_dry_run")
        wallet = str(self.config.get("finance.crypto_wallet_public") or "").strip()
        if not wallet:
            blockers.append("finance.crypto_wallet_public_missing")
        if bool(self.config.get("finance.simulate_rewards_in_dry_run", False)):
            blockers.append("simulate_rewards_forbidden")
        integrations = integrations if integrations is not None else self.integration_report()
        claimable = []
        for name, info in integrations.items():
            if not info.get("ok"):
                continue
            rules = info.get("automation") or {}
            if rules.get("automation_allowed") is False:
                continue
            claimable.append(name)
        if live and not claimable:
            blockers.append("no_claimable_live_platform")
        consistency = audit_config(self.config)
        warnings = list(consistency.get("warnings") or [])
        signing = self._signing_wallet_status()
        if live and not signing.get("loaded"):
            # Soft warning — BasedAgents may still work; TaskMarket/BountyBook need the key
            warnings.append("signing_wallet_missing_run_SET_ETH_KEY_bat")
        # Merge consistency blockers that apply in live (avoid dupes)
        for b in consistency.get("blockers") or []:
            if b not in blockers and (live or b == "finance.simulate_rewards_in_dry_run_must_be_false"):
                if b.startswith("live_") or "placeholder" in b or "simulate" in b:
                    blockers.append(b)
        return {
            "live": live,
            "ready": live and not blockers and bool(claimable),
            "blockers": blockers,
            "warnings": warnings,
            "claimable_platforms": claimable,
            "signing_wallet": signing,
            "auto_accept": bool(self.config.get("analysis.auto_accept", False)),
            "verify_on_chain": bool(self.config.get("finance.verify_on_chain", True)),
            "bank_provider_configured": self._bank_provider is not None,
            "bank_iban_set": bool(str(self.config.get("finance.bank_iban") or "").strip()),
            "consistency": consistency,
        }

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

    def integration_report(self, *, force: bool = False) -> dict[str, Any]:
        # Short cache so the control panel can poll without re-probing every platform each tick
        now = time.time()
        if (
            not force
            and self._integrations_cache is not None
            and (now - self._integrations_cache_at) < 45.0
        ):
            return self._integrations_cache
        report = verify_integrations(self.platforms)
        self._integrations_cache = report
        self._integrations_cache_at = now
        return report

    def acknowledge_alert(self, alert_id: int) -> bool:
        ok = self.db.acknowledge_alert(int(alert_id))
        if ok:
            self.journal.record("alert_ack", "ok", alert_id=alert_id)
        return ok

    def _platform_account_status(self) -> dict[str, Any]:
        try:
            from centbot.discovery.platform_registration import registration_status

            return registration_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "accounts": {}}

    def _consistency_report(self) -> dict[str, Any]:
        from centbot.core.consistency import audit_config

        return audit_config(self.config)

    def _signing_wallet_status(self) -> dict[str, Any]:
        try:
            from centbot.windows.eth_key import signing_wallet_status

            return signing_wallet_status(self.root)
        except Exception as exc:  # noqa: BLE001
            return {"loaded": False, "error": str(exc)}

    def _ensure_basedagents_identity(self) -> dict[str, Any]:
        """Create/register BasedAgents keypair when missing (live claim prerequisite)."""
        conn = self.platforms.get("basedagents")
        if not conn or not getattr(conn, "enabled", False):
            return {"ok": False, "skipped": True, "reason": "platform_disabled"}
        ident = getattr(conn, "identity", None)
        # Keypair without agent_id still needs /register/complete
        if ident is not None and getattr(ident, "agent_id", None):
            return {"ok": True, "skipped": True, "reason": "already_loaded", "agent_id": ident.agent_id}
        if not bool(self.config.get("platforms.basedagents.auto_register", True)):
            return {"ok": False, "skipped": True, "reason": "auto_register_disabled"}
        try:
            from centbot.windows.register_based import register

            name = str((self.config.section("operator") or {}).get("full_name") or "CENTBOT")
            result = register(name=name.split()[0] if name else "CENTBOT", root=self.root)
            if result.get("ok"):
                # Reload connector identity
                from centbot.platforms.auth_basedagents import resolve_identity

                cfg = self.config.section("platforms").get("basedagents", {}) or {}
                conn.identity = resolve_identity(cfg, self.credentials.get)
                self.journal.record("basedagents_register", "ok", agent_id=result.get("agent_id"))
            else:
                self.journal.record("basedagents_register", "error", result=result)
            return result
        except Exception as exc:  # noqa: BLE001
            # Surface API body when register/complete fails (was opaque 400 before)
            body = getattr(exc, "body", None)
            self.journal.record("basedagents_register", "error", error=str(exc), body=body)
            return {"ok": False, "error": str(exc), "body": body}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Persist safe settings to config/local.yaml from the control panel."""
        if not isinstance(patch, dict):
            return {"ok": False, "error": "invalid_patch"}
        # Never accept secrets through settings API
        forbidden = {"bank_password", "seed_phrase", "mnemonic", "card_cvv", "private_key"}
        flat = json.dumps(patch).lower()
        if any(f in flat for f in forbidden):
            return {"ok": False, "error": "forbidden_secret_in_patch"}
        allowed_top = {"system", "analysis", "finance", "android", "notifications", "operator", "discovery", "platforms"}
        clean = {k: v for k, v in patch.items() if k in allowed_top}
        # finance: only public fields
        if "finance" in clean and isinstance(clean["finance"], dict):
            fin_allow = {
                "bank_iban",
                "bank_swift_bic",
                "bank_currency",
                "bank_account_holder",
                "bank_provider_base_url",
                "crypto_wallet_public",
                "crypto_network",
                "preferred_crypto",
                "reconcile_payments",
                "verify_on_chain",
            }
            clean["finance"] = {k: v for k, v in clean["finance"].items() if k in fin_allow}
        path = self.config.save_local(clean)
        # Prove durability: path must be under install root, not PyInstaller _MEI temp
        resolved = str(path.resolve())
        self.journal.record("settings_update", "ok", path=resolved, keys=list(clean.keys()))
        return {
            "ok": True,
            "path": resolved,
            "persisted": path.exists(),
            "settings": self.status().get("settings"),
        }

    def status(self) -> dict[str, Any]:
        counts = {
            r["status"]: r["c"]
            for r in self.db.fetchall("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status")
        }
        alerts = self.db.fetchall(
            "SELECT id, level, message, source, created_at FROM alerts WHERE acknowledged=0 ORDER BY id DESC LIMIT 20"
        )
        recent = self.db.fetchall(
            "SELECT id, title, platform, status, reward_amount, reward_currency, expected_profit, "
            "priority, updated_at, raw_json FROM tasks ORDER BY updated_at DESC LIMIT 40"
        )
        active = self.db.fetchall(
            "SELECT id, title, platform, status, reward_amount, reward_currency, expected_profit, "
            "priority, updated_at, raw_json FROM tasks WHERE status IN "
            "('eligible','accepted','running','submitted','verified','needs_repair',"
            "'dry_run_accepted','dry_run_completed','skipped') "
            "ORDER BY priority DESC, updated_at DESC LIMIT 40"
        )
        for bucket in (recent, active):
            for r in bucket:
                reason = None
                raw_s = r.pop("raw_json", None)
                try:
                    raw_o = json.loads(raw_s) if isinstance(raw_s, str) else raw_s
                    if isinstance(raw_o, dict):
                        reason = raw_o.get("reject_reason") or raw_o.get("skip_reason")
                except (TypeError, json.JSONDecodeError):
                    reason = None
                if reason:
                    r["reject_reason"] = reason
        balances = self.ledger.balances()
        income = self.ledger.income_history(15)
        # Fresh monitor sample when idle (run_forever keeps _last_snapshot hot)
        snap = self._last_snapshot or self.monitor.snapshot().to_dict()
        journal_tail: list[dict[str, Any]] = []
        journal_path = self.config.path_from("logging.directory", "logs") / "actions.jsonl"
        if journal_path.exists():
            try:
                lines = journal_path.read_text(encoding="utf-8").splitlines()[-40:]
                for line in lines:
                    try:
                        journal_tail.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except OSError:
                pass
        integrations = self.integration_report()
        readiness = self.live_readiness(integrations)
        platform_rows = self.ledger.platform_profitability()
        awaiting_pay = counts.get("submitted", 0) + counts.get("verified", 0)
        in_progress = (
            counts.get("running", 0)
            + counts.get("accepted", 0)
            + counts.get("dry_run_accepted", 0)
            + counts.get("needs_repair", 0)
        )
        completed = counts.get("completed", 0) + counts.get("paid", 0) + counts.get("dry_run_completed", 0)
        bank_income = [r for r in income if r.get("kind") == "bank"]
        crypto_income = [r for r in income if r.get("kind") == "crypto"]
        return {
            "mode": self.config.get("system.mode"),
            "live": self.config.is_live() and not self._controlled_mode,
            "controlled": self._controlled_mode,
            "cycles": self._cycles,
            "running": self._running,
            "emergency": self.emergency.is_active(),
            "live_readiness": readiness,
            "workers": {
                "active": self.pool.active_count(),
                "ids": self.pool.active_ids(),
                "max": int(self.config.get("system.max_parallel_tasks", 4) or 4),
            },
            "tasks": {
                "total": sum(counts.values()),
                "eligible": counts.get("eligible", 0) + counts.get("accepted", 0),
                "running": counts.get("running", 0),
                "completed": counts.get("completed", 0),
                "rejected": counts.get("rejected", 0),
                "skipped": counts.get("skipped", 0),
                "awaiting_payment": awaiting_pay,
                "in_progress": in_progress,
                "done": completed,
                "active_count": len(active),
                "by_status": counts,
            },
            "finance": {
                "profit": balances.get("profit", 0),
                "bank": balances.get("bank", 0),
                "crypto": balances.get("crypto", 0),
                "cash": balances.get("cash", 0),
                "currency": self.config.get("finance.default_currency", "USD"),
                "wallet_public_set": bool(self.config.get("finance.crypto_wallet_public")),
                "bank_iban_set": bool(str(self.config.get("finance.bank_iban") or "").strip()),
                "bank_provider_configured": self._bank_provider is not None,
                "verify_on_chain": bool(self.config.get("finance.verify_on_chain", True)),
                "income": income,
                "last_bank": bank_income[0] if bank_income else None,
                "last_crypto": crypto_income[0] if crypto_income else None,
                "confirmed_payments_total": float(balances.get("bank", 0) or 0) + float(balances.get("crypto", 0) or 0),
            },
            "system": snap,
            "alerts": alerts,
            "recent_tasks": recent,
            "active_tasks": active,
            "journal": journal_tail[-25:],
            "android": self.emulator.status(),
            "distributor": self.distributor.status(),
            "browser": {
                "enabled": bool(self.config.get("browser.enabled", True)),
                "headless": bool(self.config.get("browser.headless", True)),
            },
            "ai": {"enabled": bool(self.config.get("ai.enabled")), "ollama": self.ollama.available()},
            "integrations": {
                k: {
                    "ok": bool(v.get("ok")),
                    "live": bool(v.get("live")),
                    "sample_task_count": v.get("sample_task_count") or 0,
                    "error": v.get("error"),
                    "note": v.get("note"),
                }
                for k, v in integrations.items()
            },
            "platforms": platform_rows,
            "platform_accounts": self._platform_account_status(),
            "discovery": {
                "sources_ok": sum(1 for v in integrations.values() if v.get("ok")),
                "sources_total": len(integrations),
                "tasks_seen": sum(counts.values()),
                "auto_register_allowed": bool(self.config.get("discovery.auto_register_allowed", False)),
            },
            "settings": {
                "mode": self.config.get("system.mode"),
                "auto_accept": bool(self.config.get("analysis.auto_accept", False)),
                "min_expected_profit": self.config.get("analysis.min_expected_profit"),
                "bank_iban_set": bool(str(self.config.get("finance.bank_iban") or "").strip()),
                "crypto_wallet_set": bool(str(self.config.get("finance.crypto_wallet_public") or "").strip()),
                "signing_wallet": self._signing_wallet_status(),
                "android_enabled": bool(self.config.get("android.enabled", True)),
                "android_max": int(self.config.get("android.max_emulators", 4) or 4),
                "max_parallel_tasks": int(self.config.get("system.max_parallel_tasks", 6) or 6),
                "operator_email": (self.config.section("operator") or {}).get("email") or "",
            },
            "consistency": self._consistency_report(),
        }

    def _reclassify_soft_rejects(self) -> int:
        """Turn hard Noraidīts (claimable=false) into skipped/eligible under current rules."""
        from centbot.platforms.hydrate import task_from_row
        from centbot.platforms.taskmarket import _is_auto_claimable

        rows = self.db.fetchall("SELECT * FROM tasks WHERE status=?", ("rejected",))
        if not rows:
            return 0
        tm = self.platforms.get("taskmarket")
        worker = None
        if tm is not None and getattr(tm, "wallet", None) is not None:
            worker = tm.wallet.address
        changed = 0
        for row in rows:
            raw: dict[str, Any] = {}
            try:
                parsed = json.loads(row["raw_json"]) if isinstance(row.get("raw_json"), str) else row.get("raw_json")
                if isinstance(parsed, dict):
                    raw = parsed
            except (TypeError, json.JSONDecodeError):
                raw = {}
            reason = str(raw.get("reject_reason") or "")
            soft_reasons = {
                "not_directly_claimable",
                "stake_payment_required",
                "hire_reserved",
                "not_claim_mode",
                "already_claimed",
            }
            if reason and reason not in soft_reasons and row.get("platform") != "taskmarket":
                continue
            claimable = True
            if row.get("platform") == "taskmarket":
                blob = raw.get("task") if isinstance(raw.get("task"), dict) else {}
                claimable = _is_auto_claimable(blob, worker) if blob else False
            elif reason == "not_directly_claimable":
                claimable = False
            task_obj = task_from_row(row)
            item = self.analysis.analyze(
                {
                    **row,
                    "claimable": 1 if claimable else 0,
                    "available": row.get("available", 1),
                    "funded": row.get("funded", 0),
                    "raw_json": raw,
                    "_task": task_obj,
                }
            )
            store = {k: v for k, v in item.items() if k not in ("_task", "is_new", "reject_reason", "automation_allowed")}
            if item.get("reject_reason"):
                raw = dict(raw)
                raw["reject_reason"] = item["reject_reason"]
                store["raw_json"] = raw
            self.db.upsert_task(store)
            changed += 1
        if changed:
            self.journal.record("reclassify", "ok", reopened=changed)
        return changed

    def discover_and_analyze(self) -> list[dict[str, Any]]:
        if not self.rate_limiter.allow():
            self.journal.record("discover", "rate_limited")
            return []
        # Probe configured extras + auto-discover known public boards (real URLs only)
        try:
            from centbot.discovery.new_platforms import auto_attach_reachable, scout_configured_extras

            attach = auto_attach_reachable(self.config, persist=True)
            self.journal.record(
                "platform_discover",
                "ok" if attach.get("ok") else "error",
                attached=attach.get("attached"),
                probed=attach.get("probed"),
                skipped=attach.get("skipped"),
            )
            # Rebuild platform map if new extras attached
            if attach.get("attached"):
                from centbot.platforms.registry import build_platforms

                self.platforms = build_platforms(self.config, credential_getter=self.credentials.get)
                self.scanner.platforms = self.platforms
                self.acceptor.platforms = self.platforms
                self.submitter.platforms = self.platforms
            for scout in scout_configured_extras(self.config):
                self.journal.record(
                    "platform_scout",
                    "ok" if scout.get("ok") else "error",
                    **{k: v for k, v in scout.items() if k not in {"item", "candidate"}},
                )
        except Exception as exc:  # noqa: BLE001
            self.journal.record("platform_scout", "error", error=str(exc))
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
        # Reclassify rows stuck as Noraidīts from older claimable=false hard-rejects
        self._reclassify_soft_rejects()
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

            result_out = outcome.get("result", {}) if isinstance(outcome.get("result"), dict) else {}
            # Programming: never auto-submit without sufficient independent verification
            indep = (result_out.get("output") or {}).get("independent") if isinstance(result_out.get("output"), dict) else None
            if str(task_row.get("category") or result_out.get("category") or "") == "programming":
                if not isinstance(indep, dict) or not indep.get("ok") or indep.get("skipped"):
                    self.journal.record(
                        "submit_result",
                        "blocked",
                        task_id=task_id,
                        reason="insufficient_independent_verification",
                        independent=indep,
                    )
                    self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("completed", utcnow(), task_id))
                    return {
                        "ok": False,
                        "task_id": task_id,
                        "evidence": str(evidence),
                        "inputs": inputs,
                        "error": "insufficient_independent_verification",
                    }
            if self._controlled_mode:
                self.journal.record("submit_result", "blocked_controlled", task_id=task_id)
                return {"ok": ok, "task_id": task_id, "evidence": str(evidence), "inputs": inputs, "submit": "blocked_controlled"}
            submit_payload = {
                "summary": f"CENTBOT completed {task_row.get('title')}",
                "evidence": str(evidence),
                "output": result_out.get("output"),
                "content": result_out.get("output"),
            }
            task_obj = task_row.get("_task") or task_from_row(task_row)
            submit_row = {**task_row, "_task": task_obj}
            submit_result = self.submitter.submit(submit_row, submit_payload)
            submit_mode = submit_result.get("mode")
            platform_submit_ok = bool(submit_result.get("ok")) and submit_mode != "dry_run"
            if submit_mode == "dry_run":
                self.journal.record("submit_result", "dry_run", task_id=task_id, result=submit_result)
                self.db.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                    ("dry_run_completed", utcnow(), task_id),
                )
                final_ok = bool(outcome.get("ok"))
            elif platform_submit_ok:
                self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("submitted", utcnow(), task_id))
                self.journal.record("submit_result", "ok", task_id=task_id, result=submit_result)
                final_ok = True
            else:
                # Local work may be done, but platform submit failed — do not claim platform success
                self.journal.record("submit_result", "error", task_id=task_id, result=submit_result)
                final_ok = False if self.config.is_live() else bool(outcome.get("ok"))
                if self.config.is_live():
                    self.db.execute(
                        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                        ("submit_failed", utcnow(), task_id),
                    )
            self.journal.record(
                "execute",
                "ok" if final_ok else "failed",
                task_id=task_id,
                evidence=str(evidence),
                platform_submit_ok=platform_submit_ok,
                mode=self.config.get("system.mode"),
            )
            return {
                "ok": final_ok,
                "task_id": task_id,
                "evidence": str(evidence),
                "inputs": inputs,
                "submit": submit_result,
                "local_execution_ok": bool(outcome.get("ok")),
                "platform_submit_ok": platform_submit_ok,
            }
        else:
            self.optimizer.learn_from_reward(task_row["platform"], False)
            self.rejection_repair.handle(task_id, reason=str(outcome.get("error") or "failed"))
        self.journal.record("execute", status, task_id=task_id, evidence=str(evidence))
        return {"ok": ok, "task_id": task_id, "evidence": str(evidence), "inputs": inputs, "local_execution_ok": ok}

    def schedule_eligible(self) -> int:
        from centbot.platforms.hydrate import task_from_row

        # Live never schedules dry_run_accepted rows as if they were claimed
        if self.config.is_live() and not self._controlled_mode:
            statuses = ("eligible", "accepted", "needs_repair")
        else:
            statuses = ("eligible", "accepted", "dry_run_accepted", "needs_repair")
        rows = self.db.fetchall(
            f"SELECT * FROM tasks WHERE status IN ({','.join('?' for _ in statuses)}) ORDER BY priority DESC",
            statuses,
        )
        launched = 0
        # Reset per-cycle skip map so a newly set ETH key is picked up next cycle
        self._accept_blocked_platforms = {}
        for row in sort_by_priority(rows):
            if not self.pool.has_capacity():
                break
            if self.emergency.is_active():
                break
            # Skip dry-run practice rows when operating live
            if self.config.is_live() and str(row.get("status") or "").startswith("dry_run"):
                continue
            task_obj = task_from_row(row)
            row = {**row, "_task": task_obj}
            if row["status"] == "eligible":
                if self._controlled_mode or self.config.is_dry_run():
                    # Local practice only — never confuse with a real platform claim
                    self.db.execute(
                        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                        ("dry_run_accepted", utcnow(), row["id"]),
                    )
                    row["status"] = "dry_run_accepted"
                else:
                    # Live: always attempt real accept. Surface platform errors; never fake ok.
                    # Force acceptor out of dry_run whenever intentional live (not controlled).
                    self.acceptor.dry_run = False
                    self.submitter.dry_run = False
                    self.config.set("analysis.auto_accept", True)
                    if isinstance(self.acceptor.config, dict):
                        self.acceptor.config["auto_accept"] = True
                    # Skip platforms already known blocked this cycle (e.g. wallet_required spam)
                    blocked = getattr(self, "_accept_blocked_platforms", {}) or {}
                    if row.get("platform") in blocked:
                        continue
                    accept = self.acceptor.accept({**row, "status": "eligible", "_task": task_obj})
                    if not accept.get("ok") or accept.get("mode") == "dry_run":
                        err = (
                            accept.get("error")
                            or accept.get("reason")
                            or accept.get("message")
                            or "accept_failed"
                        )
                        self.journal.record(
                            "accept",
                            "error",
                            task_id=row["id"],
                            platform=row.get("platform"),
                            external_id=row.get("external_id"),
                            error=str(err),
                            reason=str(accept.get("reason") or err),
                            user_action=accept.get("user_action") or accept.get("hint"),
                            handoff_url=accept.get("handoff_url"),
                            result=accept,
                        )
                        alert_msg = f"Accept failed {row.get('platform')}:{row.get('external_id')} — {err}"
                        if str(err) == "wallet_required":
                            alert_msg = (
                                f"{row.get('platform')}: nav ETH signing key — "
                                "SET_ETH_KEY.bat (TaskMarket). BasedAgents strada bez ta."
                            )
                            self._accept_blocked_platforms = {
                                **blocked,
                                str(row.get("platform")): "wallet_required",
                            }
                        if str(err) == "basedagents_identity_missing":
                            alert_msg = (
                                "basedagents: identity_missing — palaid REGISTER_BASED.bat vai FIX_LIVE.bat, tad STOP+START"
                            )
                            self._accept_blocked_platforms = {
                                **blocked,
                                str(row.get("platform")): "basedagents_identity_missing",
                            }
                            # Opportunistic auto-register once per process
                            if not getattr(self, "_based_register_attempted", False):
                                self._based_register_attempted = True
                                try:
                                    self._ensure_basedagents_identity()
                                except Exception as reg_exc:  # noqa: BLE001
                                    self.journal.record("basedagents_register", "error", error=str(reg_exc))
                        if str(err) == "stake_payment_required":
                            alert_msg = (
                                "TaskMarket: claim stake (x402/Base USDC) — šis darbs izlaists; "
                                "auto-claim tikai bez stake."
                            )
                        if str(err) == "not_claim_mode":
                            alert_msg = (
                                "TaskMarket: nav Claim režīms (bounty/pitch) — /claim neder; izlaists."
                            )
                        if str(err) == "hire_reserved":
                            alert_msg = (
                                "TaskMarket: hire rezervēts citam worker — izlaists."
                            )
                        if str(err) == "signature_mismatch":
                            alert_msg = (
                                "TaskMarket: paraksts nesakrīt ar maka adresi — pārbaudi SET_ETH_KEY.bat."
                            )
                        # Deduplicate identical open alerts
                        existing = self.db.fetchone(
                            "SELECT id FROM alerts WHERE acknowledged=0 AND message=? LIMIT 1",
                            (alert_msg,),
                        )
                        if not existing:
                            soft = {
                                "wallet_required",
                                "basedagents_identity_missing",
                                "stake_payment_required",
                                "not_claim_mode",
                                "hire_reserved",
                            }
                            lvl = "info" if str(err) in soft else "warning"
                            self.db.add_alert(lvl, alert_msg, source="accept")
                        # Permanent platform-policy failures: stop retrying every cycle
                        permanent = {
                            "index_only",
                            "index_only_no_accounts",
                            "human_authorization_required",
                            "not_directly_claimable",
                            "register_api_unsupported",
                            "stake_payment_required",
                            "not_claim_mode",
                            "hire_reserved",
                        }
                        if str(err) in permanent or str(accept.get("reason") or "") in permanent:
                            # Soft outcomes — Izlaists, not Noraidīts
                            self.db.execute(
                                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                                ("skipped", utcnow(), row["id"]),
                            )
                            raw = row.get("raw_json")
                            try:
                                raw_obj = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
                            except (TypeError, json.JSONDecodeError):
                                raw_obj = {}
                            raw_obj["reject_reason"] = str(err)
                            self.db.execute(
                                "UPDATE tasks SET raw_json=? WHERE id=?",
                                (json.dumps(raw_obj, default=str), row["id"]),
                            )
                        # Skip to next suitable task instead of faking success
                        continue
                    self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("accepted", utcnow(), row["id"]))
                    self.ledger.update_platform_stats(row["platform"], accepted=1)
                    row["status"] = "accepted"
            assignment = self.distributor.assign(row)
            if not assignment.get("ok"):
                self.journal.record("distribute", "skipped", task_id=row["id"], result=assignment)
                continue
            row = {**row, "_worker": assignment}
            self.distributor.rebalance_roles()

            def _run(task=row, assign=assignment):
                try:
                    return self.execute_task(task)
                finally:
                    self.distributor.release(str(task.get("id")))

            self.pool.submit(row["id"], int(row.get("priority") or 50), _run)
            launched += 1
        return launched

    def reconcile_payments(self) -> list[dict[str, Any]]:
        """Book income only after verified crypto on-chain or bank provider evidence."""
        if self._controlled_mode:
            self.journal.record("payment_check", "blocked_controlled")
            return []
        if self.config.is_dry_run():
            self.journal.record("payment_check", "blocked_dry_run")
            return []
        if not self.config.get("finance.reconcile_payments", True):
            return []
        require_tx = bool(self.config.get("finance.require_tx_hash", True))
        updates: list[dict[str, Any]] = []
        pending = self.db.fetchall(
            "SELECT * FROM tasks WHERE status IN ('submitted','verified') "
            "AND status NOT LIKE 'dry_run%' ORDER BY updated_at DESC LIMIT 40"
        )
        expected_iban = str(self.config.get("finance.bank_iban") or "").strip() or None
        for row in pending:
            conn = self.platforms.get(row["platform"])
            if not conn or not hasattr(conn, "check_payment"):
                continue
            try:
                pay = conn.check_payment(row["external_id"])
            except Exception as exc:  # noqa: BLE001
                self.journal.record("payment_check", "error", task_id=row["id"], error=str(exc))
                continue
            pay_dict = pay if isinstance(pay, dict) else None
            method_hint = ""
            if isinstance(pay_dict, dict):
                nested = pay_dict.get("payment") if isinstance(pay_dict.get("payment"), dict) else pay_dict
                method_hint = str(nested.get("method") or nested.get("payment_method") or nested.get("rail") or "").lower()
            is_bank = method_hint in {"bank", "bank_transfer", "sepa", "wise", "paypal", "fiat"}
            wallet = str(self.config.get("finance.crypto_wallet_public") or "").strip() or None
            if is_bank:
                if not expected_iban:
                    self.journal.record("payment_check", "pending", task_id=row["id"], reason="recipient_iban_required")
                    continue
                if self._bank_provider is None:
                    self.journal.record("payment_check", "pending", task_id=row["id"], reason="bank_provider_not_configured")
                    continue
            elif not wallet:
                self.journal.record("payment_check", "pending", task_id=row["id"], reason="recipient_required")
                continue
            confirmed = confirm_payment(
                pay_dict,
                require_tx=require_tx,
                expected_wallet=wallet,
                expected_amount=float(row.get("reward_amount") or 0) or None,
                min_confirmations=int(self.config.get("finance.min_confirmations", 1)),
                verify_chain=bool(self.config.get("finance.verify_on_chain", True)),
                expected_iban=expected_iban,
                provider_client=self._bank_provider,
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
                    method=confirmed.get("method"),
                )
                continue
            amount = float(confirmed.get("amount") or row.get("reward_amount") or 0)
            transfer = confirmed.get("transfer") if isinstance(confirmed.get("transfer"), dict) else None
            if transfer and transfer.get("amount") is not None:
                amount = float(transfer["amount"])
            method = str(confirmed.get("method") or ("bank" if is_bank else "crypto")).lower()
            if method == "bank":
                currency = str(confirmed.get("currency") or row.get("reward_currency") or "EUR")
                tx_ref = str(confirmed.get("provider_tx_id") or confirmed.get("bank_reference") or confirmed.get("tx_hash"))
                recorded = self.ledger.record_bank_reward(
                    amount=amount,
                    currency=currency,
                    platform=row["platform"],
                    task_id=row["id"],
                    tx_ref=tx_ref,
                )
            else:
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
                updates.append(
                    {
                        "task_id": row["id"],
                        "tx_ref": tx_ref,
                        "amount": amount,
                        "currency": currency,
                        "method": method,
                    }
                )
                self.journal.record("payment_received", "ok", task_id=row["id"], tx_ref=tx_ref, amount=amount, method=method)
            else:
                self.journal.record("payment_received", "duplicate", task_id=row["id"], tx_ref=tx_ref, method=method)
        return updates

    def _sync_android_workers(self) -> None:
        """Bind ADB serials to distributor when android.enabled; else zero Android capacity."""
        if not bool(self.config.get("android.enabled", True)):
            for i in range(1, 5):
                wid = f"android_{i}"
                if wid in self.distributor.workers:
                    self.distributor.workers[wid].capacity = 0
                    self.distributor.workers[wid].serial = None
            return
        try:
            from centbot.android.adb import devices

            serials = devices(str(self.config.get("android.adb_path", "adb")))
        except Exception:  # noqa: BLE001
            serials = []
        # Restore capacity for configured slots then bind
        max_slots = int(self.config.get("android.max_emulators", 4) or 4)
        for i in range(1, 5):
            wid = f"android_{i}"
            if wid in self.distributor.workers:
                self.distributor.workers[wid].capacity = 1 if i <= max_slots else 0
        self.distributor.bind_android_serials(serials)

    def cycle_once(self) -> dict[str, Any]:
        if self.emergency.is_active():
            return {"ok": False, "reason": "emergency_stop"}
        snap = self.monitor.snapshot()
        self._last_snapshot = snap.to_dict()
        self.db.set_state("system_snapshot", self._last_snapshot)
        for msg in self.monitor.warnings(snap):
            self.db.add_alert("warning", msg, source="monitor")
            self.journal.record("monitor_warning", "warn", message=msg)

        self._sync_android_workers()
        readiness = self.live_readiness() if self.config.is_live() else {"live": False, "ready": False}
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
        balances = self.ledger.balances()
        summary = {
            "ok": True,
            "cycle": self._cycles,
            "analyzed": len(analyzed),
            "launched": launched,
            "submissions": len(submission_updates),
            "payments": len(payments),
            "profit": balances.get("profit"),
            "bank_balance": balances.get("bank"),
            "crypto_balance": balances.get("crypto"),
            "active_workers": self.pool.active_count(),
            "mode": self.config.get("system.mode"),
            "live_ready": readiness.get("ready"),
            "live_blockers": readiness.get("blockers") if self.config.is_live() else [],
            "controlled": self._controlled_mode,
        }
        # Persist evidence snapshot each cycle (facts only)
        try:
            from centbot.quality.ops_report import build_operations_report, write_operations_report

            report = build_operations_report(
                db=self.db,
                ledger=self.ledger,
                journal_dir=self.config.path_from("logging.directory", "logs"),
                mode=str(self.config.get("system.mode")),
                live=self.config.is_live() and not self._controlled_mode,
            )
            report["cycle"] = summary
            write_operations_report(self.root / "data" / "ops" / "operations-report.json", report)
        except Exception as exc:  # noqa: BLE001
            self.journal.record("ops_report", "error", error=str(exc))
        self.journal.record("cycle", "ok", **{k: v for k, v in summary.items() if k != "live_blockers"})
        return summary

    def run_forever(self) -> None:
        from centbot.runtime_paths import bootstrap_runtime, ssl_verify_path

        bootstrap_runtime()
        verify = ssl_verify_path()
        if isinstance(verify, str) and "_MEI" in verify.replace("\\", "/"):
            log.error("TLS still pointing at PyInstaller temp (%s) — delete CENTBOT.exe and use START.bat/FIX_NOW.bat", verify)
            self.db.add_alert(
                "critical",
                "TLS CA is _MEI temp path — run FIX_NOW.bat (kill CENTBOT.exe, use Python)",
                source="tls",
            )
        elif isinstance(verify, str):
            log.info("TLS CA bundle: %s", verify)

        self._running = True
        pid_path = self.config.path_from("system.pid_file", "data/centbot.pid")
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(__import__("os").getpid()), encoding="utf-8")

        if self.config.get("dashboard.enabled", True):
            from centbot.dashboard.app import read_dashboard_state

            app = create_dashboard(
                self.status,
                lambda: self.emergency.trigger("dashboard"),
                ack_alert=self.acknowledge_alert,
                update_settings=self.update_settings,
            )
            preferred = int(self.config.get("dashboard.port", 8787))
            host = str(self.config.get("dashboard.host", "127.0.0.1"))
            try:
                start_dashboard_thread(app, host, preferred)
                state = read_dashboard_state()
                actual_port = int(state.get("port") or preferred)
                if state.get("bumped"):
                    log.warning(
                        "Dashboard port %s busy — using %s instead (%s)",
                        preferred,
                        actual_port,
                        state.get("reason"),
                    )
                log.info("Dashboard on http://%s:%s", "127.0.0.1" if host in {"0.0.0.0", "::"} else host, actual_port)
            except OSError as exc:
                log.error("Dashboard failed to bind: %s", exc)
                self.db.add_alert("critical", f"Dashboard bind failed: {exc}", source="dashboard")

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
        """Controlled discovery trial: real feeds + local practice; never claims/submits/payments."""
        return self.run_live_trial(execute_local=True, controlled=True)

    def run_live_trial(self, *, execute_local: bool = True, controlled: bool = False) -> dict[str, Any]:
        """Pull real platform feeds and optionally practice-execute locally.

        ``controlled=True`` is only for ``--controlled-live`` / test harnesses and
        forces dry_run. Default ``controlled=False`` respects the user's configured
        mode (including intentional live) and never silently overrides it.
        """
        from centbot.sandbox.isolated import sandbox_backend_info

        if controlled:
            self.enter_controlled_mode()
        dry = self.config.is_dry_run()
        report: dict[str, Any] = {
            "integrations": self.integration_report(),
            "mode": self.config.get("system.mode"),
            "claims_allowed": False
            if (controlled or self._controlled_mode)
            else ((not dry) and bool(self.config.get("analysis.auto_accept"))),
            "sandbox": sandbox_backend_info(),
            "controlled": bool(controlled or self._controlled_mode),
            "acceptor_dry_run": bool(self.acceptor.dry_run),
            "submitter_dry_run": bool(self.submitter.dry_run),
            "live_readiness": self.live_readiness(),
        }
        analyzed = self.discover_and_analyze()
        report["discovered"] = len(analyzed)
        eligible = [t for t in analyzed if t.get("status") == "eligible"]
        report["eligible"] = len(eligible)
        report["samples"] = [
            {
                "platform": t["platform"],
                "title": (t.get("title") or "")[:80],
                "reward": t.get("reward_amount"),
                "currency": t.get("reward_currency"),
            }
            for t in sort_by_priority(eligible)[:10]
        ]
        results = []
        if execute_local:
            for row in sort_by_priority(eligible)[: int(self.config.get("system.max_parallel_tasks", 4))]:
                # Practice mark only when dry_run/controlled — never invent a live claim
                mark = "dry_run_accepted" if (dry or controlled or self._controlled_mode) else "accepted"
                if mark == "accepted" and not self.config.is_live():
                    mark = "dry_run_accepted"
                if self.config.is_live() and not (controlled or self._controlled_mode):
                    # Live trial without controlled does not auto-claim; discovery only unless caller schedules
                    continue
                self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (mark, utcnow(), row["id"]))
                results.append(self.execute_task(row))
        report["executed"] = results
        report["payments"] = [] if (controlled or self._controlled_mode or dry) else self.reconcile_payments()
        balances = self.ledger.balances()
        report["profit"] = balances.get("profit")
        report["bank_balance"] = balances.get("bank")
        report["crypto_balance"] = balances.get("crypto")
        report["income"] = self.ledger.income_history(20)
        report["platform_stats"] = self.ledger.platform_profitability()
        report["verification"] = {
            "live_discovery": report["discovered"] > 0,
            "local_execution_attempted": bool(execute_local) and bool(results),
            "local_execution_ok": any(r.get("ok") for r in results) if results else None,
            "reward_received": bool(report["payments"]),
            "reward_blocker": (
                "controlled_dry_run_no_external_actions"
                if (controlled or self._controlled_mode)
                else ("dry_run_no_claim" if dry else ("no_settled_payout_observed" if not report["payments"] else None))
            ),
            "external_accept_blocked": bool(controlled or self._controlled_mode or self.acceptor.dry_run),
            "external_submit_blocked": bool(controlled or self._controlled_mode or self.submitter.dry_run),
            "external_payment_booking_blocked": bool(controlled or self._controlled_mode or dry),
        }
        self.journal.record(
            "live_trial",
            "ok",
            discovered=report["discovered"],
            eligible=report["eligible"],
            executed=len(results),
            controlled=bool(controlled or self._controlled_mode),
            reward_received=bool(report["payments"]),
            mode=report["mode"],
        )
        return report

    def operations_report(self) -> dict[str, Any]:
        from centbot.quality.ops_report import build_operations_report

        return build_operations_report(
            db=self.db,
            ledger=self.ledger,
            journal_dir=self.config.path_from("logging.directory", "logs"),
            mode=str(self.config.get("system.mode")),
            live=self.config.is_live() and not self._controlled_mode,
        )

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
