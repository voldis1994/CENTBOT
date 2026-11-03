@echo off
REM CENTBOT stop script (Windows)
SETLOCAL
cd /d "%~dp0"

if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  echo [CENTBOT] Stopping PID %PID%...
  taskkill /PID %PID% /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
  echo [CENTBOT] Stopped.
) else (
  echo [CENTBOT] No PID file. Attempting to stop by process name...
  taskkill /FI "WINDOWTITLE eq CENTBOT*" /T /F >nul 2>&1
  echo [CENTBOT] Stop request sent.
)
ENDLOCAL
