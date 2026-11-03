@echo off
REM CENTBOT STOP — kill engine, exe, and CENTBOT-managed emulators
SETLOCAL EnableExtensions
cd /d "%~dp0"

echo [CENTBOT] Stopping CENTBOT.exe / engine / managed emulators...

REM Always kill broken/old exe first (source of _MEI TLS errors)
taskkill /IM CENTBOT.exe /F >nul 2>&1

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  set "PY=python"
)

"%PY%" -m centbot.windows.stop
set "EC=%ERRORLEVEL%"

if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID %PID% /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)

REM Clear dashboard state so next start rebinds cleanly
if exist data\runtime\dashboard.json del /f /q data\runtime\dashboard.json >nul 2>&1

echo [CENTBOT] Stop complete.
ENDLOCAL
exit /b %EC%
