"""python -m centbot.windows.start"""

from __future__ import annotations

import json
import sys

from centbot.windows.launcher import full_start, setup_incomplete


def main() -> int:
    if setup_incomplete():
        print(json.dumps({"ok": False, "error": "setup_incomplete", "hint": "Run SETUP.bat first"}, indent=2))
        return 2
    report = full_start(skip_emulators="--skip-emulators" in sys.argv)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
