"""Automatic result verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def verify_result(result: dict[str, Any], workdir: Path) -> dict[str, Any]:
    issues: list[str] = []
    if not result.get("ok"):
        issues.append(result.get("error") or "execution_failed")
    artifacts = result.get("artifacts") or []
    if not artifacts:
        issues.append("no_artifacts")
    for a in artifacts:
        if not Path(a).exists():
            issues.append(f"missing:{a}")
        elif Path(a).stat().st_size == 0:
            issues.append(f"empty:{a}")
    report_path = Path(workdir) / "test_report.json"
    if report_path.exists():
        import json

        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not report.get("ok", True):
            issues.append("test_report_failed")
    return {"ok": not issues, "issues": issues}
