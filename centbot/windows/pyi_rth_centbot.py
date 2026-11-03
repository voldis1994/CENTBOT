# PyInstaller runtime hook — runs before any centbot import when frozen.
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = Path(sys.executable).resolve().parent
    os.environ.setdefault("CENTBOT_ROOT", str(root))
    try:
        os.chdir(root)
    except OSError:
        pass

    # Prefer durable cert next to exe; seed from MEIPASS / vendored if needed
    durable = root / "certs" / "cacert.pem"
    mei = getattr(sys, "_MEIPASS", None)
    sources = []
    if mei:
        sources.extend(
            [
                Path(mei) / "centbot" / "certs" / "cacert.pem",
                Path(mei) / "certs" / "cacert.pem",
                Path(mei) / "certifi" / "cacert.pem",
            ]
        )
    for src in sources:
        try:
            if src.is_file() and src.stat().st_size > 10_000:
                if not durable.is_file() or durable.stat().st_size < 10_000:
                    durable.parent.mkdir(parents=True, exist_ok=True)
                    durable.write_bytes(src.read_bytes())
                break
        except OSError:
            continue

    if durable.is_file():
        resolved = str(durable.resolve())
        os.environ["SSL_CERT_FILE"] = resolved
        os.environ["REQUESTS_CA_BUNDLE"] = resolved
        os.environ["CURL_CA_BUNDLE"] = resolved


_bootstrap()
