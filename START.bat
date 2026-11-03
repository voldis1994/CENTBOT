@echo off
REM CENTBOT START — prefer Python (reliable TLS). Old CENTBOT.exe without certs\cacert.pem is skipped.
SETLOCAL EnableExtensions
cd /d "%~dp0"

if exist data\EMERGENCY_STOP (
  echo [CENTBOT] Emergency stop active. Delete data\EMERGENCY_STOP to start.
  exit /b 1
)

REM Prefer project venv
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [CENTBOT] Python not found. Run SETUP.bat first.
  exit /b 1
)

"%PY%" -c "import yaml" >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Dependencies missing. Launching SETUP.bat ...
  call "%~dp0SETUP.bat"
  if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
)

if not exist config\local.yaml (
  echo [CENTBOT] No config\local.yaml — running SETUP wizard once...
  call "%~dp0SETUP.bat"
)

if exist data\centbot.pid (
  echo [CENTBOT] Already running. Use STOP.bat first.
  exit /b 1
)

if not exist data mkdir data
if not exist logs mkdir logs
if not exist backups mkdir backups
if not exist sandbox mkdir sandbox
if not exist data\runtime mkdir data\runtime
if not exist certs mkdir certs

REM Seed durable TLS CA next to install (fixes _MEI certifi errors without exe rebuild)
if not exist "certs\cacert.pem" if exist "centbot\certs\cacert.pem" copy /Y "centbot\certs\cacert.pem" "certs\cacert.pem" >nul
if not exist "certs\cacert.pem" (
  "%PY%" -c "import certifi,shutil,pathlib; p=pathlib.Path('certs'); p.mkdir(exist_ok=True); shutil.copy(certifi.where(), p/'cacert.pem'); print('[CENTBOT] seeded', p/'cacert.pem')"
)

REM Only use CENTBOT.exe if it has a durable CA beside it (otherwise Python path — no _MEI TLS bug)
set "USE_EXE="
if /I "%CENTBOT_USE_EXE%"=="1" if exist "%~dp0CENTBOT.exe" if exist "%~dp0certs\cacert.pem" set "USE_EXE=1"

if defined USE_EXE (
  echo [CENTBOT] Starting via CENTBOT.exe ...
  set "CENTBOT_ROOT=%CD%"
  "%~dp0CENTBOT.exe"
  set "EC=%ERRORLEVEL%"
  goto :done
)

if exist "%~dp0CENTBOT.exe" if not exist "%~dp0certs\cacert.pem" (
  echo [CENTBOT] Skipping old CENTBOT.exe ^(no certs\cacert.pem^) — using Python instead.
  echo           After git pull, run BUILD_EXE.bat once if you want a fresh exe.
)

echo [CENTBOT] Starting LIVE via Python ...
set "CENTBOT_ROOT=%CD%"
"%PY%" -m centbot.windows.start
set "EC=%ERRORLEVEL%"

:done
if "%EC%"=="0" (
  echo [CENTBOT] Started. Panel URL is printed above / in data\runtime\dashboard.json
) else (
  echo [CENTBOT] Start failed code %EC%. Run STOP.bat then retry. See logs\engine.stderr.log
)
ENDLOCAL
exit /b %EC%
