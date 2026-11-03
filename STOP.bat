@echo off
REM CENTBOT STOP — stop engine + CENTBOT-managed emulators only
SETLOCAL EnableExtensions
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  set "PY=python"
)

echo [CENTBOT] Stopping CENTBOT services and managed emulators...
"%PY%" -m centbot.windows.stop
set "EC=%ERRORLEVEL%"

REM Fallback PID kill if python helper unavailable
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID %PID% /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)

echo [CENTBOT] Stop complete. Other user apps were not targeted.
ENDLOCAL
exit /b %EC%
