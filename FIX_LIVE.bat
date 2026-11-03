@echo off
REM ============================================================
REM  CENTBOT FIX_LIVE — one shot: pull main + identity + Android + start
REM  Fixes: wallet_required hint, basedagents_identity, nav SDK, TLS exe
REM ============================================================
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo [CENTBOT] === FIX_LIVE 1/6 STOP ===
taskkill /IM CENTBOT.exe /F >nul 2>&1
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID !PID! /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m centbot.windows.stop >nul 2>&1
)

echo [CENTBOT] === FIX_LIVE 2/6 Pull main ===
where git >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] git missing — winget install Git.Git
  pause
  exit /b 1
)
git fetch origin main
git checkout main
git pull origin main

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"
"%PY%" -c "import yaml,certifi" >nul 2>&1
if errorlevel 1 (
  if not exist .venv\Scripts\python.exe "%PY%" -m venv .venv
  if exist .venv\Scripts\python.exe set "PY=%CD%\.venv\Scripts\python.exe"
  "%PY%" -m pip install -r requirements.txt
)

echo [CENTBOT] === FIX_LIVE 3/6 BasedAgents identity ===
"%PY%" -m centbot.windows.register_based --name CENTBOT
if errorlevel 1 echo [CENTBOT] WARNING: BasedAgents register failed — will retry later

echo [CENTBOT] === FIX_LIVE 4/7 Android SDK + AVDs ===
"%PY%" -m centbot.windows.android_sdk -y
if errorlevel 1 echo [CENTBOT] WARNING: Android incomplete — PC live lane still works

echo [CENTBOT] === FIX_LIVE 5/7 Docker sandbox ===
where docker >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] docker not on PATH — skip. Install/start Docker Desktop if you have it.
) else (
  "%PY%" -m centbot.windows.docker_sandbox
  if errorlevel 1 echo [CENTBOT] WARNING: Docker not ready — start Docker Desktop Engine, then ENSURE_DOCKER.bat
)

echo [CENTBOT] === FIX_LIVE 6/7 ETH signing key check ===
"%PY%" -m centbot.windows.eth_key status
"%PY%" -c "from centbot.windows.eth_key import signing_wallet_status; import sys; s=signing_wallet_status(); print(s.get('hint_lv','')); sys.exit(0 if s.get('loaded') else 2)"
if errorlevel 2 (
  echo.
  echo [CENTBOT] NEED ETH KEY for TaskMarket claims:
  echo           Run SET_ETH_KEY.bat now ^(hex private key, NOT seed^), then re-run FIX_LIVE.bat
  echo           Or continue — BasedAgents may still claim after identity register.
  echo.
  choice /C YN /M "Open SET_ETH_KEY.bat now"
  if errorlevel 2 goto skip_eth
  if errorlevel 1 call SET_ETH_KEY.bat
)
:skip_eth

echo [CENTBOT] === FIX_LIVE 7/7 START ===
if not exist certs mkdir certs
if exist centbot\certs\cacert.pem copy /Y centbot\certs\cacert.pem certs\cacert.pem >nul
set CENTBOT_ROOT=%CD%
set CENTBOT_USE_EXE=0
REM START.bat auto-detects Docker; do not force REQUIRE=0 when Docker exists
set SSL_CERT_FILE=%CD%\certs\cacert.pem
set REQUESTS_CA_BUNDLE=%CD%\certs\cacert.pem
set CURL_CA_BUNDLE=%CD%\certs\cacert.pem
call START.bat

echo.
echo [CENTBOT] Panel should show:
echo   - BasedAgents claims without identity_missing
echo   - Android AVD slots if INSTALL succeeded
echo   - TaskMarket OK only after SET_ETH_KEY.bat
echo   - sandbox OK when Docker Engine is running ^(ENSURE_DOCKER.bat^)
echo.
pause
ENDLOCAL
exit /b 0
