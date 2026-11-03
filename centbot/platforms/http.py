"""Shared HTTP client for live platform APIs."""

from __future__ import annotations

import time
from typing import Any

import requests

from centbot.core.logger import get_logger

log = get_logger("centbot.http")

DEFAULT_UA = "CENTBOT/1.0 (+https://github.com/voldis1994/CENTBOT; real platform client)"


class PlatformHTTPError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        user_agent: str = DEFAULT_UA,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
                **(default_headers or {}),
            }
        )
        self._etags: dict[str, str] = {}

    def url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        use_etag: bool = False,
        retries: int = 3,
        allow_statuses: tuple[int, ...] = (),
    ) -> requests.Response:
        url = self.url(path)
        hdrs = dict(headers or {})
        cache_key = f"{method.upper()} {url}"
        if use_etag and cache_key in self._etags:
            hdrs["If-None-Match"] = self._etags[cache_key]

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self.session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=hdrs,
                    timeout=self.timeout,
                )
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                    time.sleep(min(wait, 60))
                    continue
                if resp.status_code >= 500 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                if use_etag and resp.status_code == 200:
                    etag = resp.headers.get("ETag")
                    if etag:
                        self._etags[cache_key] = etag
                if resp.status_code >= 400 and resp.status_code not in allow_statuses and resp.status_code != 304:
                    try:
                        body = resp.json()
                    except Exception:
                        body = resp.text[:2000]
                    raise PlatformHTTPError(
                        f"{method.upper()} {url} -> {resp.status_code}",
                        status=resp.status_code,
                        body=body,
                    )
                return resp
            except PlatformHTTPError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise PlatformHTTPError(str(exc)) from exc
        raise PlatformHTTPError(str(last_exc) if last_exc else "request_failed")

    def get_json(self, path: str, **kwargs: Any) -> Any:
        resp = self.request("GET", path, **kwargs)
        if resp.status_code == 304:
            return {"_not_modified": True}
        if not resp.content:
            return None
        return resp.json()

    def post_json(self, path: str, json_body: Any = None, **kwargs: Any) -> Any:
        resp = self.request("POST", path, json_body=json_body, **kwargs)
        if not resp.content:
            # HTTP 2xx with empty body is not business success — callers must not assume ok
            return {"ok": False, "error": "empty_body", "status": resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {"ok": False, "error": "non_json_body", "status": resp.status_code, "text": resp.text[:2000]}
