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
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        cacert = Path(mei) / "certifi" / "cacert.pem"
        if cacert.is_file():
            os.environ.setdefault("SSL_CERT_FILE", str(cacert))
            os.environ.setdefault("REQUESTS_CA_BUNDLE", str(cacert))
            os.environ.setdefault("CURL_CA_BUNDLE", str(cacert))


_bootstrap()
