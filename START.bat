@echo off
REM CENTBOT START — Python ONLY (never auto-launch broken CENTBOT.exe)
SETLOCAL EnableExtensions EnableDelayedExpansion
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

REM Stale pid after crash blocks START forever — clear dead pid via Python helper
"%PY%" -c "from centbot.windows.launcher import clear_stale_runtime, already_running; clear_stale_runtime(); import sys; sys.exit(0 if not already_running() else 1)"
if errorlevel 1 (
  echo [CENTBOT] Already running. Run STOP.bat or FIX_NOW.bat first.
  pause
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

REM Docker sandbox ONLY if ENSURE_DOCKER.bat already proved it (data\docker.env).
REM Never force REQUIRE=1 from a bare "docker info" — missing image causes errors everywhere.
if exist "%CD%\data\docker.env" (
  for /f "usebackq tokens=1* delims==" %%A in ("%CD%\data\docker.env") do (
    if /I "%%A"=="CENTBOT_REQUIRE_CONTAINER" set "CENTBOT_REQUIRE_CONTAINER=%%B"
    if /I "%%A"=="CENTBOT_SANDBOX_BACKEND" set "CENTBOT_SANDBOX_BACKEND=%%B"
    if /I "%%A"=="CENTBOT_SANDBOX_IMAGE" set "CENTBOT_SANDBOX_IMAGE=%%B"
  )
)
if not defined CENTBOT_REQUIRE_CONTAINER set "CENTBOT_REQUIRE_CONTAINER=0"
if "%CENTBOT_REQUIRE_CONTAINER%"=="1" (
  docker info >nul 2>&1
  if errorlevel 1 (
    echo [CENTBOT] docker.env says container, but Engine down — falling back to restrictor
    set "CENTBOT_REQUIRE_CONTAINER=0"
  ) else (
    echo [CENTBOT] Docker sandbox enabled ^(ENSURE_DOCKER OK^)
  )
) else (
  echo [CENTBOT] Sandbox=restrictor ^(LIVE OK^). Optional: ENSURE_DOCKER.bat for containers.
)
set "SSL_CERT_FILE=%CD%\certs\cacert.pem"
set "REQUESTS_CA_BUNDLE=%CD%\certs\cacert.pem"
set "CURL_CA_BUNDLE=%CD%\certs\cacert.pem"

REM Load signing key (SET_ETH_KEY.bat writes data\eth.env; also credentials.enc)
set "CENTBOT_ROOT=%CD%"
if exist "%CD%\data\eth.env" (
  for /f "usebackq eol=# delims=" %%L in ("%CD%\data\eth.env") do (
    echo %%L | findstr /I "CENTBOT_ETH_PRIVATE_KEY=" >nul && set "%%L"
  )
)
"%PY%" -c "from centbot.windows.eth_key import signing_wallet_status; s=signing_wallet_status(); print('[CENTBOT] ETH:', 'OK', (s.get('address') or '')[:10] if s.get('loaded') else 'NAV — SET_ETH_KEY.bat')"

REM Load Android SDK paths (created by INSTALL_ANDROID.bat)
if exist "%CD%\data\android.env" (
  for /f "usebackq tokens=1* delims==" %%A in ("%CD%\data\android.env") do (
    if /I "%%A"=="ANDROID_HOME" set "ANDROID_HOME=%%B"
    if /I "%%A"=="ANDROID_SDK_ROOT" set "ANDROID_SDK_ROOT=%%B"
    if /I "%%A"=="CENTBOT_ADB" if not "%%B"=="" set "PATH=%%~dpB;!PATH!"
    if /I "%%A"=="CENTBOT_EMULATOR" if not "%%B"=="" set "PATH=%%~dpB;!PATH!"
  )
)
if defined ANDROID_HOME (
  set "PATH=%ANDROID_HOME%\platform-tools;%ANDROID_HOME%\emulator;%ANDROID_HOME%\cmdline-tools\latest\bin;%PATH%"
)
if not defined ANDROID_HOME if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
  set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
  set "ANDROID_SDK_ROOT=%LOCALAPPDATA%\Android\Sdk"
  set "PATH=%LOCALAPPDATA%\Android\Sdk\platform-tools;%LOCALAPPDATA%\Android\Sdk\emulator;%PATH%"
)

echo [CENTBOT] Starting LIVE with Python ^(exe disabled^)...
echo [CENTBOT] TLS CA: %SSL_CERT_FILE%

REM Emulators: default ON when android.enabled (config). Opt-out: CENTBOT_START_EMULATORS=0 or --skip-emulators
REM Force ON: CENTBOT_START_EMULATORS=1 (wins over --skip-emulators)
set "START_ARGS="
if /I "%CENTBOT_START_EMULATORS%"=="0" set "START_ARGS=--skip-emulators"
if /I "%CENTBOT_START_EMULATORS%"=="false" set "START_ARGS=--skip-emulators"
if /I "%CENTBOT_START_EMULATORS%"=="1" set "START_ARGS=--with-emulators"
if /I "%CENTBOT_START_EMULATORS%"=="true" set "START_ARGS=--with-emulators"
if /I "%CENTBOT_START_EMULATORS%"=="yes" set "START_ARGS=--with-emulators"
echo [CENTBOT] Android start args: %START_ARGS% ^(empty = follow android.enabled^)
echo [CENTBOT] Gaidu Android boot + engine ^(parasti 30-120s^) — logs parādīsies zemāk...

"%PY%" -m centbot.windows.start %START_ARGS%
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [CENTBOT] OK. Panel: http://127.0.0.1:8787/  ^(also data\runtime\dashboard.json^)
  if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
    echo [CENTBOT] ADB devices:
    "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" devices -l
  )
) else (
  echo [CENTBOT] Start failed %EC%. See logs\engine.stderr.log
  echo [CENTBOT] Try: STOP.bat  then  FIX_NOW.bat  /  FULL_SYSTEM.bat / INSTALL_ANDROID.bat
  if exist logs\engine.stderr.log (
    echo ---- last stderr lines ----
    powershell -NoProfile -Command "Get-Content -Path 'logs\engine.stderr.log' -Tail 25 -ErrorAction SilentlyContinue"
  )
  pause
)
ENDLOCAL
exit /b %EC%
