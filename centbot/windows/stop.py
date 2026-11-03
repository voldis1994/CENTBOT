"""python -m centbot.windows.stop"""

from __future__ import annotations

import json

from centbot.windows.launcher import stop_engine


def main() -> int:
    report = stop_engine()
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
