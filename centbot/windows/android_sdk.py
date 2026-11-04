"""Locate / install Android SDK tools and CENTBOT AVDs on Windows.

Prefers official Google cmdline-tools (no full Android Studio required).
Falls back to winget Google.AndroidStudio when download fails.

Default SDK root: %LOCALAPPDATA%\\Android\\Sdk
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# Official Google cmdline-tools package (Windows). Bump when Google retires the build.
CMDLINE_TOOLS_URL = (
    "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
)
SDK_PACKAGES = [
    "platform-tools",
    "emulator",
    "platforms;android-30",
    "system-images;android-30;google_apis;x86_64",
]


def candidate_sdk_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(key, "").strip()
        if val:
            roots.append(Path(val))
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    roots.extend(
        [
            Path(local) / "Android" / "Sdk" if local else home / "AppData" / "Local" / "Android" / "Sdk",
            home / "AppData" / "Local" / "Android" / "Sdk",
            home / "Android" / "Sdk",
            Path("C:/Android/Sdk"),
        ]
    )
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


def default_sdk_root() -> Path:
    for r in candidate_sdk_roots():
        if r.exists():
            return r
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "Android" / "Sdk"
    return Path.home() / "AppData" / "Local" / "Android" / "Sdk"


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def resolve_sdk_tools(sdk_root: Path | None = None) -> dict[str, Any]:
    """Find adb / emulator / sdkmanager / avdmanager (PATH or SDK tree)."""
    adb = shutil.which("adb")
    emu = shutil.which("emulator")
    sdkm = shutil.which("sdkmanager")
    avdm = shutil.which("avdmanager")
    found_root: Path | None = Path(sdk_root) if sdk_root else None

    roots = [found_root] if found_root else candidate_sdk_roots()
    for root in roots:
        if root is None or not root.exists():
            continue
        found_root = found_root or root
        plat = root / "platform-tools"
        emu_dir = root / "emulator"
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
        "sdk_root": str(found_root) if found_root else None,
        "adb": adb,
        "emulator": emu,
        "sdkmanager": sdkm,
        "avdmanager": avdm,
        "ok": bool(adb and emu),
        "have_cmdline": bool(sdkm and avdm),
        "ready_for_avd": bool(adb and emu and sdkm and avdm),
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
        os.environ["ANDROID_HOME"] = root
        os.environ["ANDROID_SDK_ROOT"] = root
    # Refresh which() after PATH mutation
    refreshed = resolve_sdk_tools(Path(root) if root else None)
    return {"ok": True, "added": added, "ANDROID_HOME": os.environ.get("ANDROID_HOME"), **refreshed}


def write_android_env(tools: dict[str, Any], *, root: Path | None = None) -> Path | None:
    """Persist SDK paths for START.bat (data/android.env)."""
    from centbot.runtime_paths import install_root

    base = Path(root) if root else install_root()
    env_path = base / "data" / "android.env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    sdk = tools.get("sdk_root") or ""
    lines = [
        f"ANDROID_HOME={sdk}",
        f"ANDROID_SDK_ROOT={sdk}",
        f"CENTBOT_ADB={tools.get('adb') or ''}",
        f"CENTBOT_EMULATOR={tools.get('emulator') or ''}",
    ]
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return env_path
    except OSError:
        return None


def persist_android_config(tools: dict[str, Any]) -> dict[str, Any]:
    """Write adb/emulator absolute paths into config/local.yaml when present."""
    try:
        from centbot.core.config import Config

        cfg = Config()
        adb = tools.get("adb") or "adb"
        emu = tools.get("emulator") or "emulator"
        # Prefer absolute paths so START works without relying on user PATH
        try:
            from pathlib import Path as _P

            if adb and _P(adb).is_file():
                adb = str(_P(adb).resolve())
            if emu and _P(emu).is_file():
                emu = str(_P(emu).resolve())
        except OSError:
            pass
        patch = {
            "android": {
                "enabled": True,
                "adb_path": adb,
                "emulator_path": emu,
            }
        }
        if tools.get("sdk_root"):
            patch["android"]["sdk_root"] = str(tools["sdk_root"])
        path = cfg.save_local(patch)
        return {"ok": True, "path": str(path), "adb_path": adb, "emulator_path": emu}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def ensure_jdk(*, assume_yes: bool = True) -> dict[str, Any]:
    """Ensure a Java JDK is available for sdkmanager (Temurin 17 via winget on Windows)."""
    from centbot.windows.hwcheck import java_jdk_status

    status = java_jdk_status()
    if status.get("ok"):
        return {"ok": True, "skipped": True, **status}
    if not sys.platform.startswith("win") or not assume_yes:
        return {"ok": False, "error": "jdk_missing", **status}
    winget = shutil.which("winget")
    if not winget:
        return {"ok": False, "error": "winget_missing", **status}
    install = _run(
        [
            winget,
            "install",
            "--id",
            "EclipseAdoptium.Temurin.17.JDK",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        timeout=1800,
    )
    refreshed = java_jdk_status()
    return {"ok": bool(refreshed.get("ok")), "install": install, **refreshed}


def persist_windows_user_path(sdk_root: Path) -> dict[str, Any]:
    """Append SDK platform-tools/emulator/cmdline-tools to the user PATH via setx (Windows)."""
    if not sys.platform.startswith("win"):
        return {"ok": True, "skipped": True, "reason": "not_windows"}
    dirs = [
        str(sdk_root / "platform-tools"),
        str(sdk_root / "emulator"),
        str(sdk_root / "cmdline-tools" / "latest" / "bin"),
    ]
    existing = os.environ.get("PATH", "")
    added: list[str] = []
    for d in dirs:
        if d.lower() not in existing.lower() and Path(d).is_dir():
            added.append(d)
    if not added:
        return {"ok": True, "added": [], "note": "already_on_path"}
    new_path = os.pathsep.join(added + [existing])
    # setx truncates at 1024 chars — only prepend our dirs to User PATH variable carefully
    try:
        user_path_proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetEnvironmentVariable('Path','User')"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        user_path = (user_path_proc.stdout or "").strip()
        pieces = [p for p in user_path.split(";") if p]
        for d in added:
            if d not in pieces:
                pieces.insert(0, d)
        joined = ";".join(pieces)
        set_proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Environment]::SetEnvironmentVariable('Path', '{joined.replace(chr(39), chr(39)+chr(39))}', 'User')",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        os.environ["PATH"] = new_path
        return {"ok": set_proc.returncode == 0, "added": added, "stderr": (set_proc.stderr or "")[-500:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc), "added": added}


def _run(cmd: list[str], *, timeout: int = 600, input_text: str | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            input=input_text,
        )
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": (proc.stdout or "")[-3000:],
            "stderr": (proc.stderr or "")[-3000:],
            "cmd": cmd,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc), "cmd": cmd}


def download_cmdline_tools(sdk_root: Path) -> dict[str, Any]:
    """Download + extract Google cmdline-tools into sdk_root/cmdline-tools/latest."""
    sdk_root.mkdir(parents=True, exist_ok=True)
    dest_latest = sdk_root / "cmdline-tools" / "latest"
    marker = dest_latest / "bin" / ("sdkmanager.bat" if sys.platform.startswith("win") else "sdkmanager")
    if marker.is_file():
        return {"ok": True, "skipped": True, "path": str(dest_latest)}

    tmp_zip = sdk_root / "_cmdline_tools.zip"
    tmp_extract = sdk_root / "_cmdline_extract"
    try:
        urllib.request.urlretrieve(CMDLINE_TOOLS_URL, tmp_zip)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"download_failed:{exc}", "url": CMDLINE_TOOLS_URL}

    try:
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract, ignore_errors=True)
        tmp_extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            zf.extractall(tmp_extract)
        # Zip usually contains a top-level "cmdline-tools" folder
        nested = tmp_extract / "cmdline-tools"
        source = nested if nested.is_dir() else tmp_extract
        if dest_latest.exists():
            shutil.rmtree(dest_latest, ignore_errors=True)
        dest_latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest_latest))
        if not marker.is_file():
            # Sometimes zip already has latest/ layout
            alt = dest_latest / "latest"
            if (alt / "bin").is_dir():
                shutil.rmtree(dest_latest, ignore_errors=True)
                shutil.move(str(alt), str(dest_latest))
        ok = marker.is_file()
        return {
            "ok": ok,
            "path": str(dest_latest),
            "error": None if ok else "sdkmanager_missing_after_extract",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"extract_failed:{exc}"}
    finally:
        try:
            if tmp_zip.exists():
                tmp_zip.unlink()
        except OSError:
            pass
        shutil.rmtree(tmp_extract, ignore_errors=True)


def accept_licenses(sdkmanager: str, sdk_root: Path) -> dict[str, Any]:
    yes = ("y\n" * 200)
    return _run(
        [sdkmanager, f"--sdk_root={sdk_root}", "--licenses"],
        timeout=600,
        input_text=yes,
    )


def install_sdk_packages(sdkmanager: str, sdk_root: Path, packages: list[str] | None = None) -> dict[str, Any]:
    pkgs = packages or SDK_PACKAGES
    return _run(
        [sdkmanager, f"--sdk_root={sdk_root}", "--install", *pkgs],
        timeout=3600,
        input_text="y\n" * 50,
    )


def install_android_stack(
    *,
    assume_yes: bool = True,
    create_avds: bool = True,
    allow_studio_fallback: bool = True,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Full Windows Android lane: cmdline-tools → packages → AVDs → env/config."""
    steps: list[dict[str, Any]] = []
    from centbot.windows.hwcheck import full_hw_report

    hw = full_hw_report()
    steps.append({"step": "hw", "result": {k: hw.get(k) for k in ("recommended_emulators", "blockers", "jdk", "virtualization", "ram", "cpu", "disk")}})

    jdk = ensure_jdk(assume_yes=assume_yes)
    steps.append({"step": "jdk", "result": jdk})

    sdk_root = default_sdk_root()
    tools = resolve_sdk_tools(sdk_root)
    steps.append({"step": "detect", "result": dict(tools)})

    # 1) Ensure cmdline-tools exist
    if not tools.get("have_cmdline"):
        dl = download_cmdline_tools(sdk_root)
        steps.append({"step": "cmdline_tools", "result": dl})
        tools = ensure_path_env(resolve_sdk_tools(sdk_root))
        if not tools.get("have_cmdline") and allow_studio_fallback and sys.platform.startswith("win") and assume_yes:
            # Direct winget — do NOT call ComponentInstaller.ensure_android_sdk (would recurse)
            winget = shutil.which("winget")
            if winget:
                studio = _run(
                    [
                        winget,
                        "install",
                        "--id",
                        "Google.AndroidStudio",
                        "-e",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ],
                    timeout=3600,
                )
                steps.append({"step": "android_studio_fallback", "result": studio})
                tools = ensure_path_env(resolve_sdk_tools())
            else:
                steps.append({"step": "android_studio_fallback", "result": {"ok": False, "error": "winget_missing"}})

    tools = ensure_path_env(resolve_sdk_tools(sdk_root if sdk_root.exists() else None))
    sdkm = tools.get("sdkmanager")
    root = Path(tools.get("sdk_root") or sdk_root)

    # 2) Licenses + packages when we have sdkmanager
    if sdkm:
        lic = accept_licenses(sdkm, root)
        steps.append({"step": "licenses", "result": {"ok": lic.get("ok") or True, "detail": lic.get("stderr", "")[:200]}})
        pkgs = install_sdk_packages(sdkm, root)
        steps.append({"step": "packages", "result": pkgs})
        tools = ensure_path_env(resolve_sdk_tools(root))
    else:
        steps.append({"step": "packages", "result": {"ok": False, "error": "sdkmanager_missing"}})

    tools = ensure_path_env(resolve_sdk_tools(root if root.exists() else None))
    steps.append({"step": "path", "result": {k: tools.get(k) for k in ("adb", "emulator", "sdkmanager", "sdk_root", "ok")}})

    # 3) AVDs
    avd_result: dict[str, Any] = {"ok": True, "skipped": True}
    if create_avds and tools.get("ok") and tools.get("have_cmdline"):
        from centbot.windows.avd import ensure_centbot_avds

        avd_result = ensure_centbot_avds(
            sdkmanager=str(tools.get("sdkmanager") or "sdkmanager"),
            avdmanager=str(tools.get("avdmanager") or "avdmanager"),
        )
        steps.append({"step": "avds", "result": avd_result})
    elif create_avds and tools.get("ok"):
        # adb+emulator present (Studio) but no cmdline — try creating with PATH tools
        from centbot.windows.avd import ensure_centbot_avds

        avd_result = ensure_centbot_avds()
        steps.append({"step": "avds", "result": avd_result})
    elif create_avds:
        avd_result = {
            "ok": False,
            "error": "sdk_tools_missing",
            "hint_lv": "INSTALL_ANDROID.bat nevarēja atrast adb/emulator. Palaid vēlreiz kā Administrators vai uzliec Android Studio.",
        }
        steps.append({"step": "avds", "result": avd_result})

    path_persist = {"ok": True, "skipped": True}
    if tools.get("sdk_root"):
        path_persist = persist_windows_user_path(Path(str(tools["sdk_root"])))
        os.environ["ANDROID_HOME"] = str(tools["sdk_root"])
        os.environ["ANDROID_SDK_ROOT"] = str(tools["sdk_root"])
        steps.append({"step": "user_path", "result": path_persist})

    env_file = write_android_env(tools, root=project_root)
    cfg = persist_android_config(tools) if tools.get("ok") else {"ok": False, "skipped": True}
    steps.append({"step": "persist", "result": {"env": str(env_file) if env_file else None, "config": cfg}})

    ok = bool(tools.get("ok")) and (bool(avd_result.get("ok")) if create_avds else True)
    return {
        "ok": ok,
        "tools": tools,
        "avds": avd_result,
        "hw": hw,
        "steps": steps,
        "env_file": str(env_file) if env_file else None,
        "ANDROID_HOME": tools.get("sdk_root"),
        "hint_lv": (
            "Android SDK gatavs — STOP.bat un START.bat, lai palaistu CENTBOT_ANDROID emulatorus."
            if ok
            else "Android SDK nav gatavs. Palaid INSTALL_ANDROID.bat vēlreiz (Administrators). Skaties steps JSON."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Install / detect Android SDK for CENTBOT")
    p.add_argument("--status", action="store_true")
    p.add_argument("--no-avd", action="store_true")
    p.add_argument("--no-studio", action="store_true", help="Do not fall back to winget Android Studio")
    p.add_argument("-y", "--yes", action="store_true", default=True)
    args = p.parse_args(argv)
    if args.status:
        print(json.dumps(ensure_path_env(), indent=2, default=str))
        return 0 if resolve_sdk_tools().get("ok") else 1
    report = install_android_stack(
        assume_yes=bool(args.yes),
        create_avds=not args.no_avd,
        allow_studio_fallback=not args.no_studio,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
