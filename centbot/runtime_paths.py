"""Install vs bundle paths — critical for PyInstaller onefile persistence.

Writable data (config/local.yaml, data/, logs/, certs/) MUST live next to CENTBOT.exe.
Bundled read-only assets live in sys._MEIPASS when frozen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SSL_VERIFY: str | None = None


def install_root() -> Path:
    """Directory that holds durable config/data/logs (next to the exe when frozen)."""
    env = (os.environ.get("CENTBOT_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # centbot/runtime_paths.py → repo root
    return Path(__file__).resolve().parents[1]


def bundle_root() -> Path:
    """Read-only assets extracted by PyInstaller (or repo root in source runs)."""
    mei = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and mei:
        return Path(mei)
    return install_root()


def ensure_install_layout() -> Path:
    """Create durable folders next to the exe; seed default.yaml if missing."""
    root = install_root()
    for name in ("config", "data", "logs", "backups", "sandbox", "certs", "data/runtime", "data/setup"):
        (root / name).mkdir(parents=True, exist_ok=True)
    default_dst = root / "config" / "default.yaml"
    default_src = bundle_root() / "config" / "default.yaml"
    if not default_dst.exists() and default_src.exists():
        try:
            default_dst.write_bytes(default_src.read_bytes())
        except OSError:
            pass
    return root


def _read_cacert_bytes() -> bytes | None:
    """Load CA bundle bytes from vendored/bundle/certifi — never trust a missing MEI path."""
    candidates: list[Path] = [
        install_root() / "certs" / "cacert.pem",
        Path(__file__).resolve().parent / "certs" / "cacert.pem",
        bundle_root() / "centbot" / "certs" / "cacert.pem",
        bundle_root() / "certs" / "cacert.pem",
        bundle_root() / "certifi" / "cacert.pem",
    ]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        candidates.append(Path(mei) / "certifi" / "cacert.pem")
        candidates.append(Path(mei) / "centbot" / "certs" / "cacert.pem")
    try:
        import certifi

        candidates.append(Path(certifi.where()))
    except Exception:  # noqa: BLE001
        pass

    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 10_000:
                return path.read_bytes()
        except OSError:
            continue

    # importlib.resources (works even when where() path is wrong)
    try:
        from importlib import resources

        data = resources.files("certifi").joinpath("cacert.pem").read_bytes()
        if data and len(data) > 10_000:
            return data
    except Exception:  # noqa: BLE001
        pass
    return None


def durable_cacert_path() -> Path | None:
    """Ensure a real cacert.pem exists next to the exe; return its path."""
    dest = install_root() / "certs" / "cacert.pem"
    try:
        if dest.is_file() and dest.stat().st_size > 10_000:
            return dest
    except OSError:
        pass
    data = _read_cacert_bytes()
    if not data:
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest if dest.is_file() else None
    except OSError:
        return None


def ssl_verify_path() -> str | bool:
    """Value for requests ``verify=`` — durable CA file, or True as last resort."""
    global _SSL_VERIFY
    if _SSL_VERIFY:
        p = Path(_SSL_VERIFY)
        if p.is_file():
            return _SSL_VERIFY
    path = durable_cacert_path()
    if path and path.is_file():
        _SSL_VERIFY = str(path.resolve())
        return _SSL_VERIFY
    return True


def fix_ssl_certificates() -> dict[str, str]:
    """Materialize durable CA bundle and force certifi/requests to use it.

    Fixes: Could not find a suitable TLS CA certificate bundle … _MEI…\\certifi\\cacert.pem
    """
    out: dict[str, str] = {}
    path = durable_cacert_path()
    if not path:
        out["error"] = "cacert_pem_not_found"
        return out

    resolved = str(path.resolve())
    os.environ["SSL_CERT_FILE"] = resolved
    os.environ["REQUESTS_CA_BUNDLE"] = resolved
    os.environ["CURL_CA_BUNDLE"] = resolved
    global _SSL_VERIFY
    _SSL_VERIFY = resolved
    out["cacert"] = resolved

    # certifi.where() often returns a broken _MEI path — override it
    try:
        import certifi

        def _where() -> str:
            return resolved

        certifi.where = _where  # type: ignore[method-assign]
        out["certifi_patched"] = "1"
    except Exception as exc:  # noqa: BLE001
        out["certifi_patch_error"] = str(exc)

    # urllib3 / requests may have already cached defaults
    try:
        import requests

        requests.utils.DEFAULT_CA_BUNDLE_PATH = resolved  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    return out


def _patch_requests_session_verify() -> None:
    """Force every requests.Session to use durable CA (covers monitor/FX/etc.)."""
    try:
        import requests

        if getattr(requests.sessions.Session.request, "_centbot_ssl_patched", False):
            return
        _orig = requests.sessions.Session.request

        def _request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            if "verify" not in kwargs or kwargs.get("verify") in (True, None):
                kwargs["verify"] = ssl_verify_path()
            return _orig(self, method, url, **kwargs)

        _request._centbot_ssl_patched = True  # type: ignore[attr-defined]
        requests.sessions.Session.request = _request  # type: ignore[method-assign]
    except Exception:  # noqa: BLE001
        pass


def bootstrap_runtime() -> Path:
    """Call once at process start (exe entry + python -m centbot)."""
    root = ensure_install_layout()
    os.environ.setdefault("CENTBOT_ROOT", str(root))
    ssl = fix_ssl_certificates()
    _patch_requests_session_verify()
    try:
        marker = root / "data" / "runtime" / "ssl.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        import json

        marker.write_text(json.dumps(ssl, indent=2), encoding="utf-8")
    except OSError:
        pass
    try:
        os.chdir(root)
    except OSError:
        pass
    return root
