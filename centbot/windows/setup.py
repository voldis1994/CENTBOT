"""python -m centbot.windows.setup — entry for SETUP.bat"""

from __future__ import annotations

import argparse
import json
import sys

from centbot.windows.installer import WindowsSetup


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CENTBOT Windows SETUP")
    p.add_argument("--yes", action="store_true", help="Confirm installs without prompts (admin still may be required)")
    p.add_argument("--ollama", action="store_true", help="Also install Ollama")
    p.add_argument("--skip-avd", action="store_true", help="Skip AVD creation")
    p.add_argument("--report", default="", help="Write JSON report path")
    args = p.parse_args(argv)

    setup = WindowsSetup(assume_yes=args.yes, install_ollama=args.ollama)
    report = setup.run(create_avds=not args.skip_avd)
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.report:
        from pathlib import Path

        Path(args.report).write_text(text, encoding="utf-8")
    # Pending confirmations are not hard failures if core verify passed
    if report.get("pending_confirmations") and not args.yes:
        return 2
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
