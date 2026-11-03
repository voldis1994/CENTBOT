@echo off
REM ============================================================
REM  CENTBOT FIX_LIVE — pull main + soft setup + START (never hard-fail Docker/ETH)
REM ============================================================
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo [CENTBOT] === 1/6 STOP ===
taskkill /IM CENTBOT.exe /F >nul 2>&1
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID !PID! /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m centbot.windows.stop >nul 2>&1
)

echo [CENTBOT] === 2/6 Pull main ===
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
"%PY%" -c "import yaml,certifi,eth_account" >nul 2>&1
if errorlevel 1 (
  if not exist .venv\Scripts\python.exe "%PY%" -m venv .venv
  if exist .venv\Scripts\python.exe set "PY=%CD%\.venv\Scripts\python.exe"
  "%PY%" -m pip install -r requirements.txt
)

echo [CENTBOT] === 3/6 BasedAgents identity ^(soft^) ===
"%PY%" -m centbot.windows.register_based --name CENTBOT
if errorlevel 1 echo [CENTBOT] INFO: BasedAgents register later — LIVE turpinas

echo [CENTBOT] === 4/6 Android SDK ^(soft^) ===
"%PY%" -m centbot.windows.android_sdk -y
if errorlevel 1 echo [CENTBOT] INFO: Android incomplete — PC lane OK

echo [CENTBOT] === 5/6 Docker + ETH ^(soft, never abort^) ===
where docker >nul 2>&1
if not errorlevel 1 (
  "%PY%" -m centbot.windows.docker_sandbox --soft
  echo [CENTBOT] INFO: Docker soft-check done ^(REQUIRE=0 ja Engine/image nav OK^)
) else (
  echo [CENTBOT] INFO: docker not on PATH — restrictor OK
  if not exist data mkdir data
  > data\docker.env echo CENTBOT_REQUIRE_CONTAINER=0
  >> data\docker.env echo CENTBOT_SANDBOX_BACKEND=restrictor_only
)

"%PY%" -m centbot.windows.eth_key status
"%PY%" -c "from centbot.windows.eth_key import signing_wallet_status; s=signing_wallet_status(); print('[CENTBOT]', s.get('hint_lv',''))"
if not exist data\eth.env if not defined CENTBOT_ETH_PRIVATE_KEY (
  echo [CENTBOT] INFO: TaskMarket vajag SET_ETH_KEY.bat — BasedAgents bez ta strada
)

echo [CENTBOT] === 6/6 START ===
if not exist certs mkdir certs
if exist centbot\certs\cacert.pem copy /Y centbot\certs\cacert.pem certs\cacert.pem >nul
set CENTBOT_ROOT=%CD%
set CENTBOT_USE_EXE=0
set SSL_CERT_FILE=%CD%\certs\cacert.pem
set REQUESTS_CA_BUNDLE=%CD%\certs\cacert.pem
set CURL_CA_BUNDLE=%CD%\certs\cacert.pem
call START.bat
set "EC=%ERRORLEVEL%"

echo.
echo [CENTBOT] Gatavs. Docker/ETH kludas ir INFO, ne avarija.
echo   SET_ETH_KEY.bat     — kad gribi TaskMarket claim
echo   ENSURE_DOCKER.bat   — kad Docker Engine Running + image
echo   Panel: http://127.0.0.1:8787/  ^(vai data\runtime\dashboard.json^)
echo.
pause
ENDLOCAL
exit /b %EC%
