"""python -m centbot.windows.start"""

from __future__ import annotations

import json
import os
import sys

from centbot.windows.launcher import full_start, setup_incomplete


def main() -> int:
    if setup_incomplete():
        print(json.dumps({"ok": False, "error": "setup_incomplete", "hint": "Run SETUP.bat first"}, indent=2))
        return 2
    argv = list(sys.argv)
    force_emu = "--with-emulators" in argv or str(os.environ.get("CENTBOT_START_EMULATORS") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    explicit_skip = "--skip-emulators" in argv
    # Requested launch always wins over --skip-emulators (requirement #7).
    if force_emu:
        skip = False
    elif explicit_skip:
        skip = True
    else:
        # Default: honour android.enabled in config (launch when enabled).
        try:
            from centbot.core.config import Config

            skip = not bool(Config().get("android.enabled", True))
        except Exception:  # noqa: BLE001
            skip = False
    report = full_start(skip_emulators=skip)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
