"""Verify execution results against the specific task's requirements."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def extract_requirements(task: dict[str, Any]) -> dict[str, Any]:
    """Pull acceptance criteria from description / raw platform fields."""
    raw = task.get("raw_json") or task.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    nested = {}
    if isinstance(raw, dict):
        nested = raw.get("task") or raw.get("job") or raw.get("bounty") or {}
    expected = (
        (nested.get("expected_output") if isinstance(nested, dict) else None)
        or (nested.get("spec", {}) or {}).get("success_condition")
        or task.get("expected_output")
        or ""
    )
    description = str(task.get("description") or "")
    reqs: list[str] = []
    for line in description.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("-", "*", "•")) or re.match(r"^\d+[.)]", s):
            reqs.append(re.sub(r"^[-*•\d.)\s]+", "", s))
    if expected:
        reqs.append(str(expected))
    # Keyword checks commonly found in agent briefs
    must_include = re.findall(r"(?:must include|required|deliverable)[:\s]+(.+)", description, re.I)
    return {
        "requirements": reqs,
        "expected_output": str(expected),
        "must_include": must_include,
        "category": task.get("category"),
        "min_artifacts": 1,
    }


def verify_against_requirements(
    task: dict[str, Any],
    result: dict[str, Any],
    workdir: Path,
) -> dict[str, Any]:
    spec = extract_requirements(task)
    issues: list[str] = []
    artifacts = [Path(a) for a in (result.get("artifacts") or []) if a]
    existing = [a for a in artifacts if a.exists() and a.stat().st_size > 0]
    if len(existing) < int(spec.get("min_artifacts") or 1):
        issues.append("insufficient_artifacts")

    # Aggregate textual evidence for requirement keyword checks
    blob_parts = [str(result.get("output") or "")]
    for path in existing:
        if path.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".md", ".py"}:
            try:
                blob_parts.append(path.read_text(encoding="utf-8", errors="ignore")[:50_000])
            except OSError:
                pass
    blob = "\n".join(blob_parts).lower()

    stop = {
        "must", "with", "that", "this", "from", "have", "should", "produce", "include",
        "short", "deliverable", "json", "output", "file", "result", "please", "using",
    }
    for req in spec.get("requirements") or []:
        # Soft check: require overlap with distinctive tokens from the requirement
        tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", req.lower()) if t not in stop]
        if len(tokens) < 2:
            continue
        hits = sum(1 for t in tokens[:8] if t in blob)
        if hits == 0:
            issues.append(f"requirement_unmatched:{req[:80]}")

    artifact_names = " ".join(a.name.lower() for a in existing)
    for phrase in spec.get("must_include") or []:
        p = str(phrase).lower().strip()
        if p and p not in blob and p not in artifact_names:
            issues.append(f"must_include_missing:{phrase[:80]}")

    # Category-specific hard checks
    cat = spec.get("category")
    if cat == "csv" and not any(p.name == "output.csv" for p in existing):
        issues.append("expected_output.csv")
    if cat == "excel" and not any(p.suffix.lower() == ".xlsx" for p in existing):
        issues.append("expected_xlsx")
    if cat == "text" and not any(p.name == "summary.json" for p in existing):
        issues.append("expected_summary.json")
    if cat == "programming" and not any(p.suffix == ".py" for p in existing):
        issues.append("expected_python_artifact")

    report = {"ok": not issues, "issues": issues, "spec": spec, "artifact_count": len(existing)}
    (Path(workdir) / "requirements_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
