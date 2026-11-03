"""Result evidence preservation."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def save_evidence(task_id: str, workdir: Path, evidence_root: Path, meta: dict[str, Any]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(evidence_root) / task_id / stamp
    dest.mkdir(parents=True, exist_ok=True)
    if Path(workdir).exists():
        for item in Path(workdir).iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    (dest / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return dest
