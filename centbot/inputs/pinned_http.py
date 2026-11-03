"""HTTP GET pinned to a pre-validated IP to avoid DNS rebinding (TOCTOU)."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def get_pinned(
    url: str,
    allowed_ips: list[str],
    *,
    timeout: float = 30.0,
    max_bytes: int = 5 * 1024 * 1024,
    headers: dict[str, str] | None = None,
    max_redirects: int = 3,
) -> dict[str, Any]:
    """Fetch ``url`` by connecting to one of ``allowed_ips`` with Host/SNI = hostname."""
    current = url
    hops = 0
    ips = list(allowed_ips)
    while hops <= max_redirects:
        parsed = urlparse(current)
        host = parsed.hostname
        if not host:
            return {"ok": False, "error": "missing_host", "url": current}
        scheme = (parsed.scheme or "https").lower()
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # Re-validate every IP still public before connect
        usable: list[str] = []
        for ip_s in ips:
            try:
                ip_obj = ipaddress.ip_address(ip_s)
            except ValueError:
                continue
            if _is_blocked_ip(ip_obj):
                continue
            usable.append(ip_s)
        if not usable:
            return {"ok": False, "error": "no_safe_ip", "url": current}
        ip = usable[0]

        hdrs = {"Host": host, "User-Agent": "CENTBOT/1.0", **(headers or {})}
        try:
            if scheme == "https":
                ctx = ssl.create_default_context()
                # Connect to pinned IP but present original hostname for SNI/certs
                raw = socket.create_connection((ip, port), timeout=timeout)
                ssock = ctx.wrap_socket(raw, server_hostname=host)
                conn: HTTPConnection | HTTPSConnection = HTTPSConnection(
                    ip, port=port, timeout=timeout, context=ctx
                )
                conn.sock = ssock
            else:
                conn = HTTPConnection(ip, port=port, timeout=timeout)

            conn.request("GET", path, headers=hdrs)
            resp = conn.getresponse()
            if resp.status in {301, 302, 303, 307, 308}:
                loc = resp.getheader("Location")
                conn.close()
                if not loc:
                    return {"ok": False, "error": "redirect_without_location", "url": current}
                from urllib.parse import urljoin

                current = urljoin(current, loc)
                hops += 1
                # Caller must re-resolve DNS for the new host; signal redirect
                return {"ok": False, "error": "redirect", "location": current, "hops": hops}
            if resp.status >= 400:
                body = resp.read(2048)
                conn.close()
                return {"ok": False, "error": f"http_{resp.status}", "body": body[:500], "url": current}

            cl = resp.getheader("Content-Length")
            if cl and int(cl) > max_bytes:
                conn.close()
                return {"ok": False, "error": "content_too_large", "content_length": int(cl)}

            buf = bytearray()
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    conn.close()
                    return {"ok": False, "error": "content_too_large", "bytes": len(buf)}
            conn.close()
            return {
                "ok": True,
                "url": current,
                "bytes": len(buf),
                "content": bytes(buf),
                "status": resp.status,
                "pinned_ip": ip,
                "hops": hops,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "url": current, "pinned_ip": ip}
    return {"ok": False, "error": "too_many_redirects", "url": current}
