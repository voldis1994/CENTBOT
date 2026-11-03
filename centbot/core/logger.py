"""Action and error logging for CENTBOT."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CONFIGURED = False


def setup_logging(log_dir: Path, level: str = "INFO", max_bytes: int = 10_485_760, backup_count: int = 10) -> logging.Logger:
    global _CONFIGURED
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("centbot")
    if _CONFIGURED:
        return root

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "centbot.log", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    app_handler.setFormatter(fmt)
    root.addHandler(app_handler)

    err_handler = logging.handlers.RotatingFileHandler(
        log_dir / "errors.log", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)
    root.addHandler(err_handler)

    _CONFIGURED = True
    return root


def get_logger(name: str = "centbot") -> logging.Logger:
    return logging.getLogger(name)


class ActionJournal:
    """Structured JSONL journal of actions and errors."""

    def __init__(self, log_dir: Path):
        self.path = Path(log_dir) / "actions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._log = get_logger("centbot.journal")

    def record(self, action: str, status: str = "ok", **payload: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "status": status,
            **payload,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        if status == "error":
            self._log.error("%s | %s", action, payload)
        else:
            self._log.info("%s | %s", action, status)
