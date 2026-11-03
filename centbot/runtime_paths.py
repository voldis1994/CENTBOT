"""Install vs bundle paths — critical for PyInstaller onefile persistence.

Writable data (config/local.yaml, data/, logs/) MUST live next to CENTBOT.exe.
Bundled read-only assets (default.yaml, panel.html) live in sys._MEIPASS when frozen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


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
    for name in ("config", "data", "logs", "backups", "sandbox", "data/runtime", "data/setup"):
        (root / name).mkdir(parents=True, exist_ok=True)
    default_dst = root / "config" / "default.yaml"
    default_src = bundle_root() / "config" / "default.yaml"
    if not default_dst.exists() and default_src.exists():
        try:
            default_dst.write_bytes(default_src.read_bytes())
        except OSError:
            pass
    return root


def fix_ssl_certificates() -> dict[str, str]:
    """Point requests/urllib at a real cacert.pem (fixes _MEI certifi missing path)."""
    out: dict[str, str] = {}
    candidates: list[Path] = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        candidates.append(Path(mei) / "certifi" / "cacert.pem")
    try:
        import certifi

        candidates.append(Path(certifi.where()))
    except Exception:  # noqa: BLE001
        pass
    candidates.append(install_root() / "certifi" / "cacert.pem")

    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                os.environ["SSL_CERT_FILE"] = str(path)
                os.environ["REQUESTS_CA_BUNDLE"] = str(path)
                os.environ["CURL_CA_BUNDLE"] = str(path)
                out["cacert"] = str(path)
                return out
        except OSError:
            continue
    out["error"] = "cacert_pem_not_found"
    return out


def bootstrap_runtime() -> Path:
    """Call once at process start (exe entry + python -m centbot)."""
    root = ensure_install_layout()
    os.environ.setdefault("CENTBOT_ROOT", str(root))
    fix_ssl_certificates()
    try:
        os.chdir(root)
    except OSError:
        pass
    return root
