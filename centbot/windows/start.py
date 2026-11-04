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
    # Default: skip Android emulator boot wait (START felt hung for minutes).
    # Pass --with-emulators or CENTBOT_START_EMULATORS=1 to launch AVDs.
    force_emu = "--with-emulators" in sys.argv or str(os.environ.get("CENTBOT_START_EMULATORS") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    skip = ("--skip-emulators" in sys.argv) or not force_emu
    report = full_start(skip_emulators=skip)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
