"""SQLite database layer for CENTBOT."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
    category TEXT,
    complexity REAL DEFAULT 0,
    reward_amount REAL DEFAULT 0,
    reward_currency TEXT DEFAULT 'USD',
    estimated_hours REAL DEFAULT 0,
    estimated_cost REAL DEFAULT 0,
    reward_probability REAL DEFAULT 0,
    expected_profit REAL DEFAULT 0,
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'discovered',
    payer_trust REAL DEFAULT 0.5,
    funded INTEGER DEFAULT 0,
    available INTEGER DEFAULT 1,
    fingerprint TEXT,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    worker TEXT,
    status TEXT,
    started_at TEXT,
    finished_at TEXT,
    evidence_path TEXT,
    error TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    submitted_at TEXT,
    checked_at TEXT,
    response_json TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    platform TEXT,
    kind TEXT NOT NULL,  -- bank | crypto | fee | expense | withdrawal
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    amount_base REAL,
    tx_ref TEXT UNIQUE,
    status TEXT DEFAULT 'recorded',
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_stats (
    platform TEXT PRIMARY KEY,
    accepted INTEGER DEFAULT 0,
    completed INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0,
    paid INTEGER DEFAULT 0,
    revenue_base REAL DEFAULT 0,
    cost_base REAL DEFAULT 0,
    losses_streak INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    source TEXT,
    message TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    destination TEXT,
    status TEXT DEFAULT 'pending_approval',
    requested_at TEXT NOT NULL,
    approved_at TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_platform ON tasks(platform);
CREATE INDEX IF NOT EXISTS idx_income_platform ON income(platform);
CREATE INDEX IF NOT EXISTS idx_income_tx ON income(tx_ref);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid or 0

    def fetchone(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def upsert_task(self, task: dict[str, Any]) -> None:
        now = utcnow()
        task = {**task, "created_at": task.get("created_at", now), "updated_at": now}
        if "raw_json" in task and not isinstance(task["raw_json"], str):
            task["raw_json"] = json.dumps(task["raw_json"], default=str)
        cols = [
            "id", "platform", "external_id", "title", "description", "category",
            "complexity", "reward_amount", "reward_currency", "estimated_hours",
            "estimated_cost", "reward_probability", "expected_profit", "priority",
            "status", "payer_trust", "funded", "available", "fingerprint",
            "raw_json", "created_at", "updated_at",
        ]
        values = [task.get(c) for c in cols]
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("id", "created_at"))
        sql = f"INSERT INTO tasks ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}"
        self.execute(sql, tuple(values))

    def set_state(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO system_state(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, default=str), utcnow()),
        )

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.fetchone("SELECT value FROM system_state WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return row["value"]

    def add_alert(self, level: str, message: str, source: str = "system") -> None:
        self.execute(
            "INSERT INTO alerts(level, source, message, created_at) VALUES(?,?,?,?)",
            (level, source, message, utcnow()),
        )

    def record_income(
        self,
        *,
        kind: str,
        amount: float,
        currency: str,
        platform: str | None = None,
        task_id: str | None = None,
        amount_base: float | None = None,
        tx_ref: str | None = None,
        status: str = "recorded",
        notes: str = "",
    ) -> bool:
        """Insert income row; returns False if tx_ref already exists (double-entry prevention)."""
        try:
            self.execute(
                "INSERT INTO income(task_id, platform, kind, amount, currency, amount_base, tx_ref, status, notes, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (task_id, platform, kind, amount, currency, amount_base if amount_base is not None else amount,
                 tx_ref, status, notes, utcnow()),
            )
            return True
        except sqlite3.IntegrityError:
            return False
