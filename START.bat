@echo off
REM CENTBOT start script (Windows)
SETLOCAL
cd /d "%~dp0"

if exist data\EMERGENCY_STOP (
  echo [CENTBOT] Emergency stop is active. Remove data\EMERGENCY_STOP to start.
  exit /b 1
)

if not exist data mkdir data
if not exist logs mkdir logs
if not exist backups mkdir backups
if not exist sandbox mkdir sandbox

if exist data\centbot.pid (
  echo [CENTBOT] PID file exists. Is CENTBOT already running? Use STOP.bat first.
  exit /b 1
)

echo [CENTBOT] Starting autonomous workstation...
start "CENTBOT" /MIN python -m centbot --config config\default.yaml
echo [CENTBOT] Started. Dashboard: http://127.0.0.1:8787
ENDLOCAL
