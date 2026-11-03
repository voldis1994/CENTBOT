"""Automatic testing helpers for task outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_artifacts(result: dict[str, Any]) -> dict[str, Any]:
    artifacts = result.get("artifacts") or []
    missing = [a for a in artifacts if not Path(a).exists()]
    return {
        "ok": result.get("ok", False) and not missing,
        "missing_artifacts": missing,
        "artifact_count": len(artifacts),
    }


def write_test_report(workdir: Path, checks: dict[str, Any]) -> Path:
    path = Path(workdir) / "test_report.json"
    path.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    return path
