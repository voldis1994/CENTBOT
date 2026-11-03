@echo off
REM CENTBOT START — engine + Android emulators + control panel
SETLOCAL EnableExtensions
cd /d "%~dp0"

if exist data\EMERGENCY_STOP (
  echo [CENTBOT] Emergency stop active. Delete data\EMERGENCY_STOP to start.
  exit /b 1
)

if not exist data\setup\progress.json (
  echo [CENTBOT] SETUP not completed. Launching SETUP.bat ...
  call "%~dp0SETUP.bat"
)

if not exist config\local.yaml (
  echo [CENTBOT] Missing config\local.yaml — running wizard...
  py -3 -m centbot.windows.wizard 2>nul || python -m centbot.windows.wizard
)

if exist data\centbot.pid (
  echo [CENTBOT] Already running ^(data\centbot.pid^). Use STOP.bat first.
  exit /b 1
)

if not exist data mkdir data
if not exist logs mkdir logs
if not exist backups mkdir backups
if not exist sandbox mkdir sandbox
if not exist data\runtime mkdir data\runtime

set "PY=python"
where py >nul 2>&1 && set "PY=py -3"

echo [CENTBOT] Starting system via launcher...
%PY% -m centbot.windows.start
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [CENTBOT] Started. Control panel: http://127.0.0.1:8787/
) else (
  echo [CENTBOT] Start failed with code %EC%
)
ENDLOCAL
exit /b %EC%
