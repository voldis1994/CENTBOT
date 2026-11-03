@echo off
REM CENTBOT START — Python ONLY (never auto-launch broken CENTBOT.exe)
SETLOCAL EnableExtensions
cd /d "%~dp0"

if exist data\EMERGENCY_STOP (
  echo [CENTBOT] Emergency stop active. Delete data\EMERGENCY_STOP to start.
  exit /b 1
)

REM Kill leftover broken exe that keeps producing _MEI TLS errors
taskkill /IM CENTBOT.exe /F >nul 2>&1

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [CENTBOT] Python not found. Run SETUP.bat first.
  exit /b 1
)

"%PY%" -c "import yaml,certifi" >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Missing deps — running pip install...
  if not exist .venv\Scripts\python.exe "%PY%" -m venv .venv
  if exist .venv\Scripts\python.exe set "PY=%CD%\.venv\Scripts\python.exe"
  "%PY%" -m pip install -r requirements.txt
)

if not exist config\local.yaml (
  echo [CENTBOT] No config\local.yaml — run SETUP.bat once for the wizard.
  exit /b 2
)

if exist data\centbot.pid (
  echo [CENTBOT] Already running. Run STOP.bat or FIX_NOW.bat first.
  exit /b 1
)

if not exist data mkdir data
if not exist logs mkdir logs
if not exist data\runtime mkdir data\runtime
if not exist certs mkdir certs
if not exist certs\cacert.pem if exist centbot\certs\cacert.pem copy /Y centbot\certs\cacert.pem certs\cacert.pem >nul
if not exist certs\cacert.pem (
  "%PY%" -c "import certifi,shutil,pathlib; p=pathlib.Path('certs'); p.mkdir(exist_ok=True); shutil.copy(certifi.where(), p/'cacert.pem')"
)

set "CENTBOT_ROOT=%CD%"
set "CENTBOT_USE_EXE=0"
set "SSL_CERT_FILE=%CD%\certs\cacert.pem"
set "REQUESTS_CA_BUNDLE=%CD%\certs\cacert.pem"
set "CURL_CA_BUNDLE=%CD%\certs\cacert.pem"

REM Load signing key for TaskMarket/BountyBook claims (created by SET_ETH_KEY.bat)
if exist "%CD%\data\eth.env" (
  for /f "usebackq tokens=1* delims==" %%A in ("%CD%\data\eth.env") do (
    if /I "%%A"=="CENTBOT_ETH_PRIVATE_KEY" set "CENTBOT_ETH_PRIVATE_KEY=%%B"
  )
)
if not defined CENTBOT_ETH_PRIVATE_KEY (
  echo [CENTBOT] WARNING: no CENTBOT_ETH_PRIVATE_KEY — TaskMarket claims will fail wallet_required.
  echo [CENTBOT] Run SET_ETH_KEY.bat once, then START.bat again.
)

echo [CENTBOT] Starting LIVE with Python ^(exe disabled^)...
echo [CENTBOT] TLS CA: %SSL_CERT_FILE%
"%PY%" -m centbot.windows.start
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [CENTBOT] OK. Open panel URL from data\runtime\dashboard.json
) else (
  echo [CENTBOT] Start failed %EC%. See logs\engine.stderr.log
)
ENDLOCAL
exit /b %EC%
