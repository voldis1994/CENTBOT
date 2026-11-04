"""Structural verification of results against task requirements (not keyword-only)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


def extract_requirements(task: dict[str, Any]) -> dict[str, Any]:
    """Pull acceptance criteria and structural constraints from the task brief."""
    raw = task.get("raw_json") or task.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    nested: dict[str, Any] = {}
    if isinstance(raw, dict):
        nested = raw.get("task") or raw.get("job") or raw.get("bounty") or {}
        if not isinstance(nested, dict):
            nested = {}
    expected = (
        nested.get("expected_output")
        or (nested.get("spec") or {}).get("success_condition")
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

    constraints: dict[str, Any] = {}
    # exact N lines
    m = re.search(r"exactly\s+(\d+)\s+lines?", description, re.I)
    if m:
        constraints["exact_lines"] = int(m.group(1))
    m = re.search(r"each\s+(\d+)\s*-\s*(\d+)\s+words?", description, re.I)
    if m:
        constraints["words_per_line"] = (int(m.group(1)), int(m.group(2)))
    # required filenames (include common media so create-tasks are verified by name)
    files = re.findall(
        r"\b([\w.\-]+\.(?:csv|json|xml|xlsx|txt|py|pdf|md|png|jpe?g|gif|webp))\b",
        description,
        re.I,
    )
    if files:
        constraints["required_files"] = sorted({Path(f).name.lower() for f in files})
    # JSON keys mentioned as `"key"` or schema key:
    keys = re.findall(r"[\"']([a-zA-Z_][\w]*)[\"']\s*:", description)
    if keys:
        constraints["json_keys"] = sorted(set(keys))
    # min rows for CSV
    m = re.search(r"(?:at least|min(?:imum)?)\s+(\d+)\s+rows?", description, re.I)
    if m:
        constraints["min_csv_rows"] = int(m.group(1))
    # programming tests must pass
    if task.get("category") == "programming" or re.search(r"unit[- ]?test|pytest", description, re.I):
        constraints["tests_must_pass"] = True

    must_include = re.findall(r"(?:must include|required|deliverable)[:\s]+(.+)", description, re.I)
    return {
        "requirements": reqs,
        "expected_output": str(expected),
        "must_include": must_include,
        "constraints": constraints,
        "category": task.get("category"),
        "min_artifacts": 1,
    }


def _read_text_artifacts(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if path.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".md", ".py"}:
            try:
                parts.append(path.read_text(encoding="utf-8", errors="ignore")[:80_000])
            except OSError:
                pass
    return "\n".join(parts)


def _check_exact_lines(text: str, n: int) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) != n:
        return [f"exact_lines_expected_{n}_got_{len(lines)}"]
    return []


def _check_words_per_line(text: str, lo: int, hi: int) -> list[str]:
    issues = []
    for i, ln in enumerate([ln for ln in text.splitlines() if ln.strip()], 1):
        wc = len(re.findall(r"\S+", ln))
        if wc < lo or wc > hi:
            issues.append(f"line_{i}_words_{wc}_not_in_{lo}-{hi}")
    return issues


def _check_csv(path: Path, min_rows: int | None = None) -> list[str]:
    issues = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
    except Exception as exc:  # noqa: BLE001
        return [f"csv_unreadable:{exc}"]
    if not rows:
        return ["csv_empty"]
    body = rows[1:] if len(rows) > 1 else []
    if min_rows is not None and len(body) < min_rows:
        issues.append(f"csv_rows_{len(body)}_lt_{min_rows}")
    return issues


def _check_json_keys(path: Path, keys: list[str]) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"json_unreadable:{exc}"]
    if not isinstance(data, dict):
        return ["json_not_object"]
    missing = [k for k in keys if k not in data]
    return [f"json_missing_key:{k}" for k in missing]


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

    # Execution must report ok for structural pass
    if not result.get("ok"):
        issues.append("execution_not_ok")

    constraints = spec.get("constraints") or {}
    text_blob = _read_text_artifacts(existing)
    output_obj = result.get("output")

    if constraints.get("exact_lines") is not None:
        # Prefer plain text artifact; else stringify summary short_summary
        candidate = text_blob
        for p in existing:
            if p.suffix.lower() == ".txt":
                candidate = p.read_text(encoding="utf-8", errors="ignore")
                break
        if isinstance(output_obj, dict) and output_obj.get("short_summary") and not any(p.suffix == ".txt" for p in existing):
            candidate = str(output_obj.get("short_summary"))
        issues.extend(_check_exact_lines(candidate, int(constraints["exact_lines"])))

    if constraints.get("words_per_line"):
        lo, hi = constraints["words_per_line"]
        candidate = text_blob
        for p in existing:
            if p.suffix.lower() in {".txt", ".md"}:
                candidate = p.read_text(encoding="utf-8", errors="ignore")
                break
        issues.extend(_check_words_per_line(candidate, lo, hi))

    required_files = {f.lower() for f in (constraints.get("required_files") or [])}
    present_names = {p.name.lower() for p in existing}
    # Also accept files present in workdir even if not listed as artifacts
    for p in Path(workdir).iterdir() if Path(workdir).exists() else []:
        if p.is_file():
            present_names.add(p.name.lower())
    for name in sorted(required_files):
        if name not in present_names:
            issues.append(f"required_file_missing:{name}")

    if constraints.get("json_keys"):
        json_paths = [p for p in existing if p.suffix.lower() == ".json"]
        if not json_paths:
            issues.append("json_artifact_missing_for_keys")
        else:
            issues.extend(_check_json_keys(json_paths[0], list(constraints["json_keys"])))

    if constraints.get("min_csv_rows") is not None:
        csv_paths = [p for p in existing if p.suffix.lower() == ".csv"] or list(Path(workdir).glob("*.csv"))
        if not csv_paths:
            issues.append("csv_missing_for_row_check")
        else:
            issues.extend(_check_csv(csv_paths[0], int(constraints["min_csv_rows"])))

    if constraints.get("tests_must_pass"):
        # Programming executor embeds returncode in output
        out = output_obj if isinstance(output_obj, dict) else {}
        if out.get("returncode", 1) != 0 and not result.get("ok"):
            issues.append("tests_did_not_pass")
        elif out.get("returncode") not in (0, None) and out.get("returncode") != 0:
            issues.append("tests_did_not_pass")

    # Deliverable path mentions
    artifact_names = " ".join(sorted(present_names))
    for phrase in spec.get("must_include") or []:
        p = str(phrase).lower().strip().strip(".")
        # If phrase names a concrete file that exists, the deliverable itself satisfies the clause
        named_in_phrase = re.findall(
            r"\b([\w.\-]+\.(?:csv|json|xml|xlsx|txt|py|pdf|md|png|jpe?g|gif|webp))\b",
            p,
        )
        if named_in_phrase and all(Path(n).name.lower() in present_names for n in named_in_phrase):
            continue
        # If phrase looks like a filename, require the file; otherwise require content evidence
        if re.search(r"\.\w{2,5}$", p):
            fname = Path(p.split()[-1]).name
            if fname not in present_names:
                issues.append(f"must_include_file_missing:{fname}")
        else:
            # Require a content clause: at least half of distinctive tokens OR exact phrase
            tokens = [t for t in re.findall(r"[a-zA-Z]{5,}", p) if t not in {"should", "include", "deliverable"}]
            blob = (text_blob + " " + str(output_obj)).lower()
            if p and p not in blob:
                if not tokens or sum(1 for t in tokens if t in blob) < max(1, (len(tokens) + 1) // 2):
                    issues.append(f"must_include_unsatisfied:{phrase[:80]}")

    # Category hard gates (structural)
    cat = spec.get("category")
    if cat == "csv" and not any(p.name == "output.csv" for p in existing):
        issues.append("expected_output.csv")
    if cat == "excel" and not any(p.suffix.lower() == ".xlsx" for p in existing):
        issues.append("expected_xlsx")
    if cat == "text" and not any(p.name == "summary.json" for p in existing):
        issues.append("expected_summary.json")
    if cat == "programming" and not any(p.suffix == ".py" for p in existing):
        issues.append("expected_python_artifact")

    # Keyword-only matching removed as a pass condition. Remaining requirement lines
    # must map to a satisfied structural constraint or an existing deliverable file.
    unconstrained = []
    for req in spec.get("requirements") or []:
        req_l = req.lower()
        if constraints.get("exact_lines") and "line" in req_l:
            continue
        if constraints.get("words_per_line") and "word" in req_l:
            continue
        if any(f in req_l for f in required_files):
            continue
        if constraints.get("tests_must_pass") and ("test" in req_l or "pytest" in req_l):
            continue
        # If requirement names a file that exists, ok
        named = re.findall(r"\b([\w.\-]+\.(?:csv|json|xml|xlsx|txt|py|pdf|md))\b", req_l)
        if named and all(n in present_names for n in named):
            continue
        # Otherwise mark as unverified narrative requirement (fail closed for >=1 distinctive claim)
        if len(re.findall(r"[a-zA-Z]{5,}", req_l)) >= 4 and not named:
            unconstrained.append(req[:80])
    if unconstrained and not constraints:
        # No structural hooks at all — fail closed rather than keyword-pass
        issues.append("no_structural_constraints_extracted")
        for u in unconstrained[:3]:
            issues.append(f"unverified_requirement:{u}")

    report = {
        "ok": not issues,
        "issues": issues,
        "spec": spec,
        "artifact_count": len(existing),
        "artifacts": [p.name for p in existing],
    }
    (Path(workdir) / "requirements_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
