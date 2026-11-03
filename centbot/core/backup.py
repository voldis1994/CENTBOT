"""Automatic system backup."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from centbot.core.logger import ActionJournal, get_logger

log = get_logger("centbot.backup")


class BackupManager:
    def __init__(self, source_db: Path, backup_dir: Path, keep: int = 14, journal: ActionJournal | None = None):
        self.source_db = Path(source_db)
        self.backup_dir = Path(backup_dir)
        self.keep = keep
        self.journal = journal
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._last_backup = 0.0

    def maybe_backup(self, interval_hours: float = 6.0) -> Path | None:
        if time.time() - self._last_backup < interval_hours * 3600:
            return None
        return self.backup_now()

    def backup_now(self) -> Path | None:
        if not self.source_db.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = self.backup_dir / f"centbot-{stamp}.db"
        shutil.copy2(self.source_db, dest)
        # Also copy WAL/SHM if present
        for suffix in ("-wal", "-shm"):
            side = Path(str(self.source_db) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(dest) + suffix))
        self._last_backup = time.time()
        self._prune()
        log.info("Backup created: %s", dest)
        if self.journal:
            self.journal.record("backup", "ok", path=str(dest))
        return dest

    def _prune(self) -> None:
        files = sorted(self.backup_dir.glob("centbot-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[self.keep :]:
            old.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(old) + suffix).unlink(missing_ok=True)
