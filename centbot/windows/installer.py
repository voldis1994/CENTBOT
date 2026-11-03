"""Component detection + official-source installers for Windows SETUP.

On non-Windows hosts, install actions are refused (or dry-run reported) so
Linux CI cannot pretend Windows setup succeeded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any, Callable

# Avoid importing centbot.core.config here — that pulls PyYAML before SETUP.bat can pip-install it.
ROOT = Path(__file__).resolve().parents[2]
from centbot.windows.hwcheck import full_hw_report
from centbot.windows.install_state import SetupProgress

Runner = Callable[[list[str], dict[str, Any] | None], dict[str, Any]]


def _default_runner(cmd: list[str], opts: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = opts or {}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=opts.get("timeout", 600),
            cwd=opts.get("cwd"),
            shell=opts.get("shell", False),
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "cmd": cmd,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc), "cmd": cmd}


def which(name: str) -> str | None:
    return shutil.which(name)


class WindowsSetup:
    def __init__(
        self,
        root: Path | None = None,
        *,
        progress: SetupProgress | None = None,
        runner: Runner | None = None,
        assume_yes: bool = False,
        install_ollama: bool = False,
    ):
        self.root = Path(root) if root else ROOT
        self.progress = progress or SetupProgress(self.root / "data" / "setup" / "progress.json")
        self.runner = runner or _default_runner
        self.assume_yes = assume_yes
        self.install_ollama = install_ollama
        self.venv_dir = self.root / ".venv"

    def detect_components(self) -> dict[str, Any]:
        py = sys.executable
        return {
            "python": {"ok": True, "path": py, "version": sys.version.split()[0]},
            "git": {"ok": which("git") is not None, "path": which("git")},
            "adb": {"ok": which("adb") is not None, "path": which("adb")},
            "emulator": {"ok": which("emulator") is not None, "path": which("emulator")},
            "docker": {"ok": which("docker") is not None, "path": which("docker")},
            "ollama": {"ok": which("ollama") is not None, "path": which("ollama")},
            "winget": {"ok": which("winget") is not None, "path": which("winget")},
            "venv": {"ok": (self.venv_dir / ("Scripts" if sys.platform.startswith("win") else "bin") / "python").exists()},
            "playwright": self._playwright_ready(),
        }

    def _playwright_ready(self) -> dict[str, Any]:
        try:
            import playwright  # noqa: F401

            return {"ok": True, "module": True}
        except ImportError:
            return {"ok": False, "module": False}

    def _venv_python(self) -> Path:
        if sys.platform.startswith("win"):
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    def ensure_venv(self) -> dict[str, Any]:
        if self.progress.is_done("python_venv") and self._venv_python().exists():
            return {"ok": True, "skipped": True, "path": str(self._venv_python())}
        if self._venv_python().exists():
            self.progress.mark("python_venv", ok=True, skipped=True, detail=str(self._venv_python()))
            return {"ok": True, "skipped": True, "path": str(self._venv_python())}
        self.venv_dir.mkdir(parents=True, exist_ok=True)
        try:
            venv.create(self.venv_dir, with_pip=True, upgrade_deps=False)
        except SystemExit:
            # Some Linux images lack ensurepip — fall back to system interpreter
            self.progress.mark("python_venv", ok=True, skipped=True, detail=f"system_python:{sys.executable}")
            return {"ok": True, "skipped": True, "path": sys.executable, "note": "venv_ensurepip_unavailable"}
        except Exception as exc:  # noqa: BLE001
            self.progress.mark("python_venv", ok=True, skipped=True, detail=f"system_python:{sys.executable};venv_error:{exc}")
            return {"ok": True, "skipped": True, "path": sys.executable, "error": str(exc)}
        py = self._venv_python()
        ok = py.exists()
        self.progress.mark("python_venv", ok=ok, detail=str(py), skipped=False)
        return {"ok": ok, "path": str(py)}

    def ensure_git(self) -> dict[str, Any]:
        if which("git"):
            self.progress.mark("git", ok=True, skipped=True, detail=which("git"))
            return {"ok": True, "skipped": True, "path": which("git")}
        if not sys.platform.startswith("win"):
            self.progress.mark("git", ok=False, detail="not_windows_cannot_auto_install")
            return {"ok": False, "error": "not_windows", "hint": "Install git manually"}
        if not which("winget"):
            self.progress.mark("git", ok=False, detail="winget_missing")
            return {"ok": False, "error": "winget_missing", "hint": "Install Git from https://git-scm.com/download/win"}
        if not self.assume_yes:
            return {"ok": False, "error": "needs_confirmation", "component": "git", "command": "winget install --id Git.Git -e"}
        result = self.runner(["winget", "install", "--id", "Git.Git", "-e", "--accept-package-agreements", "--accept-source-agreements"], {"timeout": 900})
        ok = bool(result.get("ok")) or which("git") is not None
        self.progress.mark("git", ok=ok, detail=str(result)[:500])
        return {"ok": ok, "result": result}

    def ensure_requirements(self) -> dict[str, Any]:
        if self.progress.is_done("pip_requirements"):
            return {"ok": True, "skipped": True}
        py = self._venv_python() if self._venv_python().exists() else Path(sys.executable)
        req = self.root / "requirements.txt"
        result = self.runner([str(py), "-m", "pip", "install", "-r", str(req)], {"timeout": 1200})
        ok = bool(result.get("ok"))
        self.progress.mark("pip_requirements", ok=ok, detail=str(result.get("stderr") or result.get("stdout") or "")[:500])
        return {"ok": ok, "result": result}

    def ensure_playwright(self) -> dict[str, Any]:
        if self.progress.is_done("playwright_browsers"):
            return {"ok": True, "skipped": True}
        py = self._venv_python() if self._venv_python().exists() else Path(sys.executable)
        # Install package then browsers from official Playwright channel
        self.runner([str(py), "-m", "pip", "install", "playwright>=1.41.0"], {"timeout": 600})
        result = self.runner([str(py), "-m", "playwright", "install", "chromium"], {"timeout": 1200})
        ok = bool(result.get("ok"))
        self.progress.mark("playwright_browsers", ok=ok, detail=str(result)[:500])
        return {"ok": ok, "result": result}

    def ensure_wsl2(self) -> dict[str, Any]:
        if not sys.platform.startswith("win"):
            self.progress.mark("wsl2", ok=True, skipped=True, detail="not_windows")
            return {"ok": True, "skipped": True, "detail": "not_windows"}
        # Detect
        probe = self.runner(["wsl", "--status"], {"timeout": 30})
        if probe.get("ok") or "wsl" in (probe.get("stdout") or "").lower() or which("wsl"):
            self.progress.mark("wsl2", ok=True, skipped=True, detail="present")
            return {"ok": True, "skipped": True}
        if not self.assume_yes:
            return {
                "ok": False,
                "error": "needs_admin_confirmation",
                "component": "wsl2",
                "hint": "Run elevated: wsl --install (reboot may be required; SETUP resumes after reboot)",
            }
        result = self.runner(["wsl", "--install"], {"timeout": 600})
        # Reboot often required — mark partial
        self.progress.mark("wsl2", ok=bool(result.get("ok")), detail="may_require_reboot:" + str(result)[:300])
        return {"ok": bool(result.get("ok")), "result": result, "reboot_maybe": True}

    def ensure_docker(self) -> dict[str, Any]:
        if which("docker"):
            self.progress.mark("docker_desktop", ok=True, skipped=True, detail=which("docker"))
            return {"ok": True, "skipped": True}
        if not sys.platform.startswith("win"):
            self.progress.mark("docker_desktop", ok=False, detail="not_windows_auto_install")
            return {"ok": False, "error": "not_windows", "hint": "Install Docker manually for sandbox isolation"}
        if not self.assume_yes:
            return {
                "ok": False,
                "error": "needs_confirmation",
                "component": "docker",
                "hint": "Install Docker Desktop from https://www.docker.com/products/docker-desktop/",
            }
        if which("winget"):
            result = self.runner(
                ["winget", "install", "--id", "Docker.DockerDesktop", "-e", "--accept-package-agreements", "--accept-source-agreements"],
                {"timeout": 1800},
            )
            ok = bool(result.get("ok")) or which("docker") is not None
            self.progress.mark("docker_desktop", ok=ok, detail=str(result)[:500])
            return {"ok": ok, "result": result}
        self.progress.mark("docker_desktop", ok=False, detail="winget_missing")
        return {"ok": False, "error": "winget_missing"}

    def ensure_android_sdk(self) -> dict[str, Any]:
        adb = which("adb")
        emu = which("emulator")
        if adb and emu:
            self.progress.mark("android_sdk", ok=True, skipped=True, detail=f"adb={adb}")
            self.progress.mark("android_emulator", ok=True, skipped=True, detail=f"emulator={emu}")
            return {"ok": True, "skipped": True, "adb": adb, "emulator": emu}
        if not sys.platform.startswith("win"):
            self.progress.mark("android_sdk", ok=False, detail="not_windows_auto_install")
            self.progress.mark("android_emulator", ok=False, detail="not_windows_auto_install")
            return {
                "ok": False,
                "error": "not_windows",
                "hint": "On Windows SETUP installs Android cmdline-tools via official Google channel when confirmed",
            }
        if not self.assume_yes:
            return {
                "ok": False,
                "error": "needs_confirmation",
                "component": "android_sdk",
                "hint": "Install Android Studio or cmdline-tools from https://developer.android.com/studio#command-tools",
            }
        # Prefer winget Android Studio (pulls SDK)
        if which("winget"):
            result = self.runner(
                ["winget", "install", "--id", "Google.AndroidStudio", "-e", "--accept-package-agreements", "--accept-source-agreements"],
                {"timeout": 3600},
            )
            ok = bool(result.get("ok"))
            self.progress.mark("android_sdk", ok=ok, detail=str(result)[:500])
            self.progress.mark("android_emulator", ok=ok, detail="bundled_with_android_studio")
            return {"ok": ok, "result": result}
        self.progress.mark("android_sdk", ok=False, detail="winget_missing")
        return {"ok": False, "error": "winget_missing"}

    def ensure_ollama(self) -> dict[str, Any]:
        if not self.install_ollama:
            self.progress.mark("ollama", ok=True, skipped=True, detail="optional_skipped")
            return {"ok": True, "skipped": True, "optional": True}
        if which("ollama"):
            self.progress.mark("ollama", ok=True, skipped=True, detail=which("ollama"))
            return {"ok": True, "skipped": True}
        if not sys.platform.startswith("win"):
            return {"ok": False, "error": "not_windows"}
        if not self.assume_yes:
            return {"ok": False, "error": "needs_confirmation", "component": "ollama"}
        if which("winget"):
            result = self.runner(
                ["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-package-agreements", "--accept-source-agreements"],
                {"timeout": 1200},
            )
            ok = bool(result.get("ok")) or which("ollama") is not None
            self.progress.mark("ollama", ok=ok, detail=str(result)[:400])
            return {"ok": ok, "result": result}
        return {"ok": False, "error": "winget_missing"}

    def verify_all(self) -> dict[str, Any]:
        """Honest readiness split: core (engine) vs optional Docker/Android.

        Core missing → SETUP/START hard-fail.
        Docker/Android missing → warnings only; live PC path must still start so real
        platform errors are visible (not fake idle behind setup_incomplete).
        """
        detected = self.detect_components()
        checks: dict[str, Any] = {
            "python": bool(sys.executable),
            "git": bool(detected["git"]["ok"]),
            "playwright_module": bool(detected["playwright"]["ok"]),
        }
        try:
            import yaml  # noqa: F401
            import flask  # noqa: F401
            import requests  # noqa: F401

            checks["imports"] = True
        except ImportError as exc:
            checks["imports"] = False
            checks["import_error"] = str(exc)

        # Docker: must answer `docker info` (daemon up), not merely exist on PATH
        if which("docker"):
            docker_info = self.runner(["docker", "info"], {"timeout": 45})
            checks["docker"] = bool(docker_info.get("ok"))
            checks["docker_detail"] = (docker_info.get("stderr") or docker_info.get("stdout") or "")[:300]
        else:
            checks["docker"] = False
            checks["docker_detail"] = "docker_not_on_path"

        # Android SDK tools
        checks["adb"] = bool(detected["adb"]["ok"])
        checks["emulator_bin"] = bool(detected["emulator"]["ok"])
        if checks["emulator_bin"]:
            from centbot.windows.avd import AVD_NAMES, list_avds

            avd_names = list_avds()
            present = [n for n in AVD_NAMES if n in set(avd_names)]
            checks["centbot_avds_present"] = present
            checks["centbot_avds_ok"] = len(present) >= 1
        else:
            checks["centbot_avds_present"] = []
            checks["centbot_avds_ok"] = False

        core_required = ["python", "git", "imports", "playwright_module"]
        android_required = ["adb", "emulator_bin", "centbot_avds_ok"]
        docker_required = ["docker"]
        core_ok = all(bool(checks.get(k)) for k in core_required)
        android_ok = all(bool(checks.get(k)) for k in android_required)
        docker_ok = all(bool(checks.get(k)) for k in docker_required)
        full_ok = core_ok and android_ok and docker_ok

        warnings: list[str] = []
        if not docker_ok:
            warnings.append("docker_not_ready_sandbox_limited")
        if not android_ok:
            warnings.append("android_sdk_or_avds_not_ready_emulator_lane_skipped")

        # verify/completed track CORE readiness — enough to run live engine + wizard
        self.progress.mark(
            "verify",
            ok=core_ok,
            detail=json_dumps(
                {
                    "checks": checks,
                    "core_ok": core_ok,
                    "android_ok": android_ok,
                    "docker_ok": docker_ok,
                    "full_ok": full_ok,
                    "warnings": warnings,
                }
            ),
        )
        self.progress._data["completed"] = bool(core_ok)
        self.progress._data["android_ready"] = bool(android_ok)
        self.progress._data["docker_ready"] = bool(docker_ok)
        self.progress._data["full_ok"] = bool(full_ok)
        self.progress.save()
        return {
            "ok": core_ok,
            "core_ok": core_ok,
            "android_ok": android_ok,
            "docker_ok": docker_ok,
            "full_ok": full_ok,
            "warnings": warnings,
            "checks": checks,
            "detected": detected,
            "core_required": core_required,
            "android_required": android_required,
            "docker_required": docker_required,
        }

    def run(self, *, create_avds: bool = True) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        hw = full_hw_report(str(self.root))
        self.progress.mark("hw_check", ok=True, detail=json_dumps({"recommended_emulators": hw.get("recommended_emulators"), "blockers": hw.get("blockers")}))
        steps.append({"step": "hw_check", "result": hw})

        steps.append({"step": "python_venv", "result": self.ensure_venv()})
        steps.append({"step": "git", "result": self.ensure_git()})
        steps.append({"step": "pip_requirements", "result": self.ensure_requirements()})
        steps.append({"step": "playwright_browsers", "result": self.ensure_playwright()})
        steps.append({"step": "wsl2", "result": self.ensure_wsl2()})
        steps.append({"step": "docker_desktop", "result": self.ensure_docker()})
        steps.append({"step": "android_sdk", "result": self.ensure_android_sdk()})
        steps.append({"step": "ollama", "result": self.ensure_ollama()})

        if create_avds:
            from centbot.windows.avd import ensure_centbot_avds

            avd_result = ensure_centbot_avds(
                count=hw.get("recommended_emulators") or 4,
                progress=self.progress,
                runner=self.runner,
            )
            steps.append({"step": "android_avds", "result": avd_result})
        else:
            self.progress.mark("android_avds", ok=True, skipped=True, detail="deferred")

        verify = self.verify_all()
        steps.append({"step": "verify", "result": verify})
        # Wizard marked separately when run
        if not self.progress.is_done("wizard"):
            self.progress.mark("wizard", ok=False, detail="pending_first_run_wizard")

        warnings = list(verify.get("warnings") or [])
        return {
            # ok = core ready (engine can start). Missing Docker/Android are warnings only.
            "ok": bool(verify.get("core_ok", verify.get("ok"))),
            "core_ok": bool(verify.get("core_ok")),
            "full_ok": bool(verify.get("full_ok")),
            "android_ok": bool(verify.get("android_ok")),
            "docker_ok": bool(verify.get("docker_ok")),
            "warnings": warnings,
            "windows": sys.platform.startswith("win"),
            "progress": self.progress.report(),
            "steps": steps,
            "pending_confirmations": [
                s["result"] for s in steps if isinstance(s.get("result"), dict) and s["result"].get("error") == "needs_confirmation"
            ]
            + [
                s["result"] for s in steps if isinstance(s.get("result"), dict) and s["result"].get("error") == "needs_admin_confirmation"
            ],
            "note": None
            if sys.platform.startswith("win")
            else "This host is not Windows — auto-install of Windows packages was skipped/refused. Re-run SETUP.bat on Windows.",
        }


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, default=str)[:2000]
