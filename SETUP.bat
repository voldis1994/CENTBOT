@echo off
REM CENTBOT Windows SETUP — resumable official-component installer
SETLOCAL EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  CENTBOT SETUP
echo  Official sources only. Resumable progress.
echo ============================================
echo.

REM Prefer py launcher, then python
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [CENTBOT] Python not found. Install Python 3.11+ from https://www.python.org/downloads/windows/
  echo           Enable "Add python.exe to PATH", then re-run SETUP.bat
  pause
  exit /b 1
)

if not exist data mkdir data
if not exist data\setup mkdir data\setup
if not exist logs mkdir logs

echo [CENTBOT] Running hardware check + component install...
%PY% -m centbot.windows.setup %*
set "EC=%ERRORLEVEL%"

if exist config\local.yaml goto after_wizard
echo.
echo [CENTBOT] First-run configuration wizard...
%PY% -m centbot.windows.wizard
if errorlevel 1 (
  echo [CENTBOT] Wizard incomplete — you can re-run: python -m centbot.windows.wizard
)

:after_wizard
echo.
if "%EC%"=="0" (
  echo [CENTBOT] SETUP finished. Next: START.bat
) else (
  echo [CENTBOT] SETUP finished with issues ^(exit %EC%^).
  echo           Re-run SETUP.bat to resume. Admin/reboot steps require confirmation.
)
echo.
pause
ENDLOCAL
exit /b %EC%
