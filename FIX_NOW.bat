@echo off
REM ============================================================
REM  CENTBOT FIX_NOW — kill broken exe, pull GitHub, start Python
REM  Fixes: _MEI...\certifi\cacert.pem TLS errors forever
REM ============================================================
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo [CENTBOT] === 1/5 STOP everything ^(incl. old CENTBOT.exe^) ===
taskkill /IM CENTBOT.exe /F >nul 2>&1
taskkill /IM python.exe /FI "WINDOWTITLE eq CENTBOT*" /F >nul 2>&1
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID !PID! /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m centbot.windows.stop >nul 2>&1
)

echo [CENTBOT] === 2/5 Disable broken PyInstaller exe ===
if exist CENTBOT.exe (
  move /Y CENTBOT.exe CENTBOT.exe.BROKEN_MEI_TLS >nul
  echo         Renamed CENTBOT.exe -^> CENTBOT.exe.BROKEN_MEI_TLS
)
if exist dist\CENTBOT.exe (
  move /Y dist\CENTBOT.exe dist\CENTBOT.exe.BROKEN >nul
)

echo [CENTBOT] === 3/5 Pull latest from GitHub ===
where git >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] ERROR: git not installed. winget install Git.Git then re-run.
  pause
  exit /b 1
)
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] This folder is NOT a git repo.
  echo           Run from C:\CENTBOT after: git clone https://github.com/voldis1994/CENTBOT.git C:\CENTBOT
  pause
  exit /b 1
)
git fetch origin main
git checkout main
git pull origin main

echo [CENTBOT] === 4/5 Seed TLS cert + ensure venv deps ===
if not exist certs mkdir certs
if exist centbot\certs\cacert.pem copy /Y centbot\certs\cacert.pem certs\cacert.pem >nul

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"

"%PY%" -c "import yaml,certifi" >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Installing requirements into venv/system...
  if not exist .venv\Scripts\python.exe "%PY%" -m venv .venv
  if exist .venv\Scripts\python.exe set "PY=%CD%\.venv\Scripts\python.exe"
  "%PY%" -m pip install -r requirements.txt
)
if not exist certs\cacert.pem (
  "%PY%" -c "import certifi,shutil,pathlib; p=pathlib.Path('certs'); p.mkdir(exist_ok=True); shutil.copy(certifi.where(), p/'cacert.pem'); print('seeded', p/'cacert.pem')"
)

if not exist config\local.yaml (
  echo [CENTBOT] WARNING: config\local.yaml missing — restore from backup or run SETUP.bat wizard once.
)

echo [CENTBOT] === 5/5 START with Python ^(NOT exe^) ===
set CENTBOT_ROOT=%CD%
set CENTBOT_USE_EXE=0
set SSL_CERT_FILE=%CD%\certs\cacert.pem
set REQUESTS_CA_BUNDLE=%CD%\certs\cacert.pem
set CURL_CA_BUNDLE=%CD%\certs\cacert.pem

call START.bat
echo.
echo [CENTBOT] If panel still shows _MEI certifi errors, you still have an old process:
echo           taskkill /IM CENTBOT.exe /F
echo           then FIX_NOW.bat again
echo.
pause
ENDLOCAL
exit /b %ERRORLEVEL%
