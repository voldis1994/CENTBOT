"""Download real task input artifacts into the work directory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.inputs")

URL_RE = re.compile(r"https?://[^\s)\]\"']+", re.I)


def _safe_name(url: str, index: int) -> str:
    path = urlparse(url).path
    name = Path(path).name or f"input_{index}"
    name = re.sub(r"[^\w.\-]+", "_", name)[:120]
    return name or f"input_{index}"


def extract_input_urls(task: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    raw = task.get("raw_json") or task.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    candidates: list[Any] = []
    for key in ("attachments", "inputs", "files", "artifacts", "input_urls"):
        val = raw.get(key)
        if isinstance(val, list):
            candidates.extend(val)
        elif isinstance(val, str):
            candidates.append(val)
    nested_task = raw.get("task") or raw.get("job") or raw.get("opportunity") or {}
    if isinstance(nested_task, dict):
        for key in ("attachments", "inputs", "files", "artifact_url", "input_url", "data_url"):
            val = nested_task.get(key)
            if isinstance(val, list):
                candidates.extend(val)
            elif isinstance(val, str):
                candidates.append(val)
        desc = nested_task.get("description") or nested_task.get("expected_output")
        if isinstance(desc, str):
            candidates.extend(URL_RE.findall(desc))

    for key in ("url", "origin_url"):
        if raw.get(key):
            # listing URL is not an input file; skip generic board links
            pass

    description = str(task.get("description") or "")
    candidates.extend(URL_RE.findall(description))

    # Explicit allow-list from task payload
    for item in candidates:
        if isinstance(item, dict):
            u = item.get("url") or item.get("href") or item.get("download_url")
        else:
            u = str(item)
        if not u or not u.startswith(("http://", "https://")):
            continue
        # Skip obvious HTML listing pages as inputs (boards)
        host = urlparse(u).netloc.lower()
        if any(h in host for h in ("jobbi.org", "basedagents.ai", "taskmarket.dev", "agentizable.ai", "bountybook.ai", "github.com")) and Path(urlparse(u).path).suffix == "":
            continue
        if u not in urls:
            urls.append(u)
    return urls


def download_task_inputs(task: dict[str, Any], workdir: Path, *, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch remote inputs into ``workdir/inputs`` and map common filenames."""
    workdir = Path(workdir)
    inputs_dir = workdir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    urls = extract_input_urls(task)
    saved: list[str] = []
    errors: list[str] = []

    # Persist task brief for executors that need text context
    brief = workdir / "task_brief.json"
    brief.write_text(
        json.dumps(
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "description": task.get("description"),
                "category": task.get("category"),
                "platform": task.get("platform"),
                "external_id": task.get("external_id"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (workdir / "input.txt").write_text(str(task.get("description") or task.get("title") or ""), encoding="utf-8")

    for i, url in enumerate(urls[:20]):
        name = _safe_name(url, i)
        dest = inputs_dir / name
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "CENTBOT/1.0"})
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            saved.append(str(dest))
            # Convenience copies for category executors
            suffix = dest.suffix.lower()
            mapping = {
                ".csv": "input.csv",
                ".xlsx": "input.xlsx",
                ".xls": "input.xlsx",
                ".json": "input.json",
                ".xml": "input.xml",
                ".pdf": "input.pdf",
                ".png": "input.png",
                ".jpg": "input.jpg",
                ".jpeg": "input.jpg",
                ".txt": "input.txt",
                ".py": "solution.py",
            }
            if suffix in mapping:
                target = workdir / mapping[suffix]
                if not target.exists():
                    target.write_bytes(dest.read_bytes())
        except Exception as exc:  # noqa: BLE001
            log.warning("Input download failed %s: %s", url, exc)
            errors.append(f"{url}: {exc}")

    manifest = {
        "ok": not errors or bool(saved),
        "urls": urls,
        "saved": saved,
        "errors": errors,
        "brief": str(brief),
    }
    (workdir / "inputs_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
