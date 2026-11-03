@echo off
REM ============================================================
REM  CENTBOT FULL_SYSTEM — complete LIVE stack in one run
REM  Keeps config\local.yaml + data\. Revolut OK for payouts.
REM  TaskMarket needs MetaMask private key (optional).
REM ============================================================
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

echo.
echo ============================================
echo  CENTBOT FULL_SYSTEM
echo  Sync + BasedAgents + Android + Docker + START
echo ============================================
echo.

REM --- 0 STOP ---
echo [1/8] STOP
taskkill /IM CENTBOT.exe /F >nul 2>&1
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID !PID! /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m centbot.windows.stop >nul 2>&1
)

REM --- 1 SYNC MAIN (fixes untracked pull errors) ---
echo [2/8] SYNC origin/main
if exist "%~dp0SYNC_MAIN.bat" (
  call "%~dp0SYNC_MAIN.bat"
) else (
  call "%~dp0FORCE_UPDATE.bat"
)
if errorlevel 1 (
  echo [CENTBOT] Sync failed — internet / git
  pause
  exit /b 1
)

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"

REM --- 2 DEPS ---
echo [3/8] Python deps
"%PY%" -c "import yaml,certifi,eth_account,nacl,flask,requests" >nul 2>&1
if errorlevel 1 (
  if not exist .venv\Scripts\python.exe "%PY%" -m venv .venv
  if exist .venv\Scripts\python.exe set "PY=%CD%\.venv\Scripts\python.exe"
  "%PY%" -m pip install -r requirements.txt
)

if not exist config\local.yaml (
  echo [CENTBOT] Nav config\local.yaml — palaid SETUP.bat wizard vienu reizi, tad FULL_SYSTEM.bat
  pause
  exit /b 2
)

REM --- 3 BasedAgents identity (required for full LIVE claims without ETH key) ---
echo [4/8] BasedAgents identity
"%PY%" -m centbot.windows.register_based --name CENTBOT
if errorlevel 1 echo        WARNING: register later — retry REGISTER_BASED.bat

REM --- 4 Android SDK / AVDs (soft) ---
echo [5/8] Android SDK + AVDs
"%PY%" -m centbot.windows.android_sdk -y
if errorlevel 1 echo        INFO: Android incomplete — PC lane still full LIVE

REM --- 5 Docker sandbox (soft; starts Desktop if possible) ---
echo [6/8] Docker sandbox
if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" (
  set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
)
"%PY%" -m centbot.windows.docker_sandbox --soft
if errorlevel 1 echo        INFO: Docker soft — restrictor OK

REM --- 6 ETH / Revolut ---
echo [7/8] ETH / Revolut
"%PY%" -c "from centbot.windows.eth_key import signing_wallet_status; s=signing_wallet_status(); print('       ', s.get('hint_lv'))"
if not exist data\eth.env (
  echo.
  echo        TaskMarket OPTIONAL: vajag MetaMask PRIVATE KEY ^(ne Revolut adresi^).
  echo        Revolut adrese = tikai payout. BasedAgents strada BEZ private key.
  echo.
  set /p WANTETH=Vai tagad SET_ETH_KEY / MetaMask? [Y/N]^> 
  if /I "!WANTETH!"=="Y" call SET_ETH_KEY.bat
)

REM --- 7 START ---
echo [8/8] START LIVE
if not exist certs mkdir certs
if exist centbot\certs\cacert.pem copy /Y centbot\certs\cacert.pem certs\cacert.pem >nul
set CENTBOT_USE_EXE=0
set SSL_CERT_FILE=%CD%\certs\cacert.pem
set REQUESTS_CA_BUNDLE=%CD%\certs\cacert.pem
set CURL_CA_BUNDLE=%CD%\certs\cacert.pem
call START.bat
set "EC=%ERRORLEVEL%"

echo.
echo ========== PILNA SISTEMA ==========
echo  Panelis:  skaties data\runtime\dashboard.json  ^(parasti http://127.0.0.1:8787/^)
echo  LIVE:     BasedAgents + Jobbi index + TaskMarket ^(ja ETH key^)
echo  Revolut:  payout adrese OK; private key Revolut nedod
echo  Docker:   ENSURE_DOCKER.bat kad Engine Running
echo  Android:  INSTALL_ANDROID.bat ja vel nav AVD
echo  Statuss:  STATUS.bat
echo ===================================
echo.
call STATUS.bat
ENDLOCAL
exit /b %EC%
