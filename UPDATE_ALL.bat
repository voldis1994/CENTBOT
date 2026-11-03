@echo off
REM ============================================================
REM  CENTBOT UPDATE_ALL — one command after git pull
REM  Pulls main, saves nothing over config/local.yaml, then FIX_LIVE
REM ============================================================
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

echo.
echo ============================================
echo  CENTBOT UPDATE_ALL
echo  1 git pull main
echo  2 BasedAgents + Android + Docker soft
echo  3 ETH check  4 START
echo  config\local.yaml NETiek pārrakstīts
echo ============================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] git missing — winget install Git.Git
  pause
  exit /b 1
)

taskkill /IM CENTBOT.exe /F >nul 2>&1
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID !PID! /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)

git fetch origin main
git checkout main
git pull origin main
if errorlevel 1 (
  echo [CENTBOT] git pull failed — pārbaudi internetu / login
  pause
  exit /b 1
)

echo.
echo [CENTBOT] Statuss pirms start:
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"

"%PY%" -c "from centbot.windows.eth_key import signing_wallet_status; print('ETH:', signing_wallet_status().get('hint_lv'))" 2>nul
where docker >nul 2>&1 && docker info >nul 2>&1 && echo Docker: Engine Running || echo Docker: nav Ready ^(OK — restrictor^)

echo.
echo [CENTBOT] Ja ETH NAV — tagad palaid SET_ETH_KEY.bat citā logā, tad turpini.
set /p CONT=Turpinat FIX_LIVE / START? [Y/N]^> 
if /I not "!CONT!"=="Y" (
  echo Apturēts. Palaid SET_ETH_KEY.bat un UPDATE_ALL.bat vēlreiz.
  pause
  exit /b 0
)

call FIX_LIVE.bat
ENDLOCAL
exit /b %ERRORLEVEL%
