"""Windows CENTBOT.exe entry — double-click live start / stop / setup / engine.

Built with: BUILD_EXE.bat  (PyInstaller onefile)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _freeze_root() -> Path:
    """Repo root when frozen (exe next to config/) or source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _freeze_root()

    import os

    os.environ["CENTBOT_ROOT"] = str(root)
    try:
        os.chdir(root)
    except OSError:
        pass
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Must run before centbot.core.config / requests imports
    from centbot.runtime_paths import bootstrap_runtime

    bootstrap_runtime()

    if "--stop" in argv or "stop" in argv:
        from centbot.windows.launcher import stop_engine

        report = stop_engine()
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("ok") else 1

    if "--setup" in argv or "setup" in argv:
        from centbot.windows.setup import main as setup_main

        return setup_main(["--yes"])

    if "--engine" in argv:
        cleaned = [a for a in argv if a != "--engine"]
        from centbot.__main__ import main as cli_main

        return cli_main(cleaned)

    if "--dashboard-only" in argv:
        from centbot.__main__ import main as cli_main

        return cli_main(["--dashboard-only"])

    if "--help" in argv or "-h" in argv:
        print(
            "CENTBOT.exe — live workstation\n"
            "  (no args)         START engine + control panel\n"
            "  --stop            STOP engine + CENTBOT emulators\n"
            "  --setup           Run SETUP components\n"
            "  --dashboard-only  Control panel only\n"
            "  --engine          Internal: run forever loop\n"
        )
        return 0

    from centbot.windows.launcher import full_start, setup_incomplete

    if setup_incomplete():
        print(
            json.dumps(
                {"ok": False, "error": "setup_incomplete", "hint": "Run CENTBOT.exe --setup or SETUP.bat"},
                indent=2,
            )
        )
        from centbot.windows.setup import main as setup_main

        setup_main(["--yes"])
        try:
            from centbot.windows.wizard import main as wizard_main

            wizard_main([])
        except SystemExit:
            pass

    force_emu = "--with-emulators" in argv or str(os.environ.get("CENTBOT_START_EMULATORS") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    if force_emu:
        skip_emu = False
    elif "--skip-emulators" in argv:
        skip_emu = True
    else:
        skip_emu = False  # honour android.enabled inside full_start / config
    report = full_start(skip_emulators=skip_emu)
    print(json.dumps(report, indent=2, default=str))
    if report.get("dashboard"):
        print(f"\n[CENTBOT] Control panel: {report.get('dashboard')}")
    local = root / "config" / "local.yaml"
    print(f"[CENTBOT] Durable config: {local} (exists={local.exists()})")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
