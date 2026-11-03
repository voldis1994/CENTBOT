"""Download real task input artifacts with SSRF protections."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.inputs")

URL_RE = re.compile(r"https?://[^\s)\]\"']+", re.I)
MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_REDIRECTS = 3
ALLOWED_SCHEMES = {"https"}  # http blocked by default
BLOCKED_HOST_SUFFIXES = (
    "jobbi.org",
    "basedagents.ai",
    "taskmarket.dev",
    "agentizable.ai",
    "bountybook.ai",
)


def _safe_name(url: str, index: int) -> str:
    path = urlparse(url).path
    name = Path(path).name or f"input_{index}"
    name = re.sub(r"[^\w.\-]+", "_", name)[:120]
    return name or f"input_{index}"


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and ip in ipaddress.ip_network("169.254.0.0/16"))
        or (ip.version == 6 and ip in ipaddress.ip_network("fc00::/7"))
    )


def validate_url_destination(url: str, *, allow_http: bool = False) -> dict[str, Any]:
    """Reject non-https, credentialed URLs, and hosts that resolve to private/LAN/metadata IPs."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    allowed = ALLOWED_SCHEMES | ({"http"} if allow_http else set())
    if scheme not in allowed:
        return {"ok": False, "error": f"scheme_not_allowed:{scheme}"}
    if parsed.username or parsed.password:
        return {"ok": False, "error": "credentials_in_url"}
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return {"ok": False, "error": "missing_host"}
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        return {"ok": False, "error": "blocked_host"}
    # Literal IP in URL
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            return {"ok": False, "error": "blocked_ip", "ip": str(ip)}
        return {"ok": True, "host": host, "ips": [str(ip)]}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return {"ok": False, "error": f"dns_failed:{exc}"}
    ips: list[str] = []
    for info in infos:
        ip_str = info[4][0]
        ips.append(ip_str)
        try:
            if _is_blocked_ip(ipaddress.ip_address(ip_str)):
                return {"ok": False, "error": "blocked_resolved_ip", "ip": ip_str, "host": host}
        except ValueError:
            return {"ok": False, "error": "invalid_resolved_ip", "ip": ip_str}
    return {"ok": True, "host": host, "ips": sorted(set(ips))}


def safe_download(url: str, dest: Path, *, timeout: float = 30.0, max_bytes: int = MAX_BYTES, allow_http: bool = False) -> dict[str, Any]:
    """GET with redirect re-validation and size cap."""
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        check = validate_url_destination(current, allow_http=allow_http)
        if not check.get("ok"):
            return {"ok": False, "error": check.get("error"), "url": current}
        try:
            with requests.get(
                current,
                timeout=timeout,
                headers={"User-Agent": "CENTBOT/1.0"},
                stream=True,
                allow_redirects=False,
            ) as resp:
                if resp.is_redirect or resp.status_code in {301, 302, 303, 307, 308}:
                    nxt = resp.headers.get("Location")
                    if not nxt:
                        return {"ok": False, "error": "redirect_without_location", "url": current}
                    # Resolve relative redirects
                    from urllib.parse import urljoin

                    current = urljoin(current, nxt)
                    if hop >= MAX_REDIRECTS:
                        return {"ok": False, "error": "too_many_redirects", "url": current}
                    continue
                resp.raise_for_status()
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > max_bytes:
                    return {"ok": False, "error": "content_too_large", "content_length": int(cl)}
                buf = bytearray()
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return {"ok": False, "error": "content_too_large", "bytes": len(buf)}
                dest.write_bytes(bytes(buf))
                return {"ok": True, "url": current, "bytes": len(buf), "path": str(dest), "hops": hop}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "url": current}
    return {"ok": False, "error": "redirect_loop", "url": current}


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

    description = str(task.get("description") or "")
    candidates.extend(URL_RE.findall(description))

    for item in candidates:
        if isinstance(item, dict):
            u = item.get("url") or item.get("href") or item.get("download_url")
        else:
            u = str(item)
        if not u or not u.startswith(("http://", "https://")):
            continue
        host = (urlparse(u).netloc or "").lower()
        path = urlparse(u).path
        if any(host == h or host.endswith("." + h) for h in BLOCKED_HOST_SUFFIXES) and Path(path).suffix == "":
            continue
        if u not in urls:
            urls.append(u)
    return urls


def download_task_inputs(task: dict[str, Any], workdir: Path, *, timeout: float = 30.0, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    """Fetch remote inputs into ``workdir/inputs`` with SSRF and size controls."""
    workdir = Path(workdir)
    inputs_dir = workdir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    urls = extract_input_urls(task)
    saved: list[str] = []
    errors: list[str] = []

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
        result = safe_download(url, dest, timeout=timeout, max_bytes=max_bytes)
        if not result.get("ok"):
            log.warning("Input download blocked/failed %s: %s", url, result.get("error"))
            errors.append(f"{url}: {result.get('error')}")
            continue
        saved.append(str(dest))
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

    manifest = {
        "ok": not errors or bool(saved),
        "urls": urls,
        "saved": saved,
        "errors": errors,
        "brief": str(brief),
        "max_bytes": max_bytes,
    }
    (workdir / "inputs_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
