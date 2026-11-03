"""Locate / install Android SDK tools and CENTBOT AVDs on Windows.

Default Studio layout:
  %LOCALAPPDATA%\\Android\\Sdk
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any


def candidate_sdk_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(key, "").strip()
        if val:
            roots.append(Path(val))
    home = Path.home()
    roots.extend(
        [
            home / "AppData" / "Local" / "Android" / "Sdk",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk",
            home / "Android" / "Sdk",
            Path("C:/Android/Sdk"),
        ]
    )
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        try:
            key = str(r.resolve()) if r.exists() else str(r)
        except OSError:
            key = str(r)
        if key in seen or not str(r).strip():
            continue
        seen.add(key)
        out.append(r)
    return out


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def resolve_sdk_tools() -> dict[str, Any]:
    """Find adb / emulator / sdkmanager / avdmanager (PATH or default SDK tree)."""
    adb = shutil.which("adb")
    emu = shutil.which("emulator")
    sdkm = shutil.which("sdkmanager")
    avdm = shutil.which("avdmanager")
    sdk_root: Path | None = None

    for root in candidate_sdk_roots():
        if not root.exists():
            continue
        sdk_root = sdk_root or root
        plat = root / "platform-tools"
        emu_dir = root / "emulator"
        # cmdline-tools may be under cmdline-tools/latest/bin or cmdline-tools/bin
        cmd_bins = [
            root / "cmdline-tools" / "latest" / "bin",
            root / "cmdline-tools" / "bin",
            root / "tools" / "bin",
        ]
        if not adb:
            hit = _first_existing([plat / "adb.exe", plat / "adb"])
            if hit:
                adb = str(hit)
        if not emu:
            hit = _first_existing([emu_dir / "emulator.exe", emu_dir / "emulator"])
            if hit:
                emu = str(hit)
        if not sdkm:
            for b in cmd_bins:
                hit = _first_existing([b / "sdkmanager.bat", b / "sdkmanager"])
                if hit:
                    sdkm = str(hit)
                    break
        if not avdm:
            for b in cmd_bins:
                hit = _first_existing([b / "avdmanager.bat", b / "avdmanager"])
                if hit:
                    avdm = str(hit)
                    break

    return {
        "sdk_root": str(sdk_root) if sdk_root else None,
        "adb": adb,
        "emulator": emu,
        "sdkmanager": sdkm,
        "avdmanager": avdm,
        "ok": bool(adb and emu),
        "have_cmdline": bool(sdkm and avdm),
    }


def ensure_path_env(tools: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepend discovered SDK bin dirs to PATH for this process."""
    tools = tools or resolve_sdk_tools()
    added: list[str] = []
    root = tools.get("sdk_root")
    if root:
        for rel in ("platform-tools", "emulator", "cmdline-tools/latest/bin", "cmdline-tools/bin"):
            p = Path(root) / rel
            if p.is_dir():
                s = str(p)
                path = os.environ.get("PATH", "")
                if s.lower() not in path.lower():
                    os.environ["PATH"] = s + os.pathsep + path
                    added.append(s)
        os.environ.setdefault("ANDROID_HOME", root)
        os.environ.setdefault("ANDROID_SDK_ROOT", root)
    return {"ok": True, "added": added, "ANDROID_HOME": os.environ.get("ANDROID_HOME"), **tools}


def install_android_stack(*, assume_yes: bool = True, create_avds: bool = True) -> dict[str, Any]:
    """Windows: winget Android Studio if needed, then create CENTBOT AVDs."""
    from centbot.windows.installer import ComponentInstaller

    steps: list[dict[str, Any]] = []
    tools = resolve_sdk_tools()
    steps.append({"step": "detect", "result": dict(tools)})

    if not tools.get("ok"):
        installer = ComponentInstaller(assume_yes=assume_yes)
        # Force confirmation path off when assume_yes
        result = installer.ensure_android_sdk()
        steps.append({"step": "ensure_android_sdk", "result": result})
        tools = resolve_sdk_tools()
        ensure_path_env(tools)

    tools = ensure_path_env(resolve_sdk_tools())
    steps.append({"step": "path", "result": {k: tools.get(k) for k in ("adb", "emulator", "sdk_root", "added")}})

    avd_result: dict[str, Any] = {"ok": True, "skipped": True}
    if create_avds and tools.get("ok"):
        from centbot.windows.avd import ensure_avds

        sdkm = tools.get("sdkmanager") or "sdkmanager"
        avdm = tools.get("avdmanager") or "avdmanager"
        avd_result = ensure_avds(sdkmanager=sdkm, avdmanager=avdm)
        steps.append({"step": "avds", "result": avd_result})
    elif create_avds:
        avd_result = {
            "ok": False,
            "error": "sdk_tools_missing",
            "hint_lv": "Uzinstalē Android Studio (winget Google.AndroidStudio), aizver/atver CMD, tad palaid INSTALL_ANDROID.bat vēlreiz.",
        }
        steps.append({"step": "avds", "result": avd_result})

    ok = bool(tools.get("ok")) and (avd_result.get("ok") if create_avds else True)
    return {
        "ok": ok,
        "tools": tools,
        "avds": avd_result,
        "steps": steps,
        "hint_lv": (
            "Android SDK gatavs — STOP.bat un START.bat, lai ielādētu emulatorus."
            if ok
            else "Android SDK nav gatavs. Palaid INSTALL_ANDROID.bat kā Administrators un gaidi Android Studio instalāciju."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Install / detect Android SDK for CENTBOT")
    p.add_argument("--status", action="store_true")
    p.add_argument("--no-avd", action="store_true")
    p.add_argument("-y", "--yes", action="store_true", default=True)
    args = p.parse_args(argv)
    if args.status:
        print(json.dumps(ensure_path_env(), indent=2, default=str))
        return 0 if resolve_sdk_tools().get("ok") else 1
    report = install_android_stack(assume_yes=bool(args.yes), create_avds=not args.no_avd)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
