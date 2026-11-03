@echo off
REM ============================================================
REM  CENTBOT UPDATE_ALL — force sync main + FIX_LIVE
REM  Survives "untracked files would be overwritten by merge"
REM ============================================================
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

echo.
echo ============================================
echo  CENTBOT UPDATE_ALL
echo  SYNC_MAIN ^(hard^) + FIX_LIVE
echo  KEEP: config\local.yaml + data\
echo ============================================
echo.

taskkill /IM CENTBOT.exe /F >nul 2>&1
if exist data\centbot.pid (
  set /p PID=<data\centbot.pid
  taskkill /PID !PID! /T /F >nul 2>&1
  del /f /q data\centbot.pid >nul 2>&1
)

REM If SYNC_MAIN.bat not present yet (old tree), inline sync
if exist "%~dp0SYNC_MAIN.bat" (
  call "%~dp0SYNC_MAIN.bat"
) else (
  where git >nul 2>&1 || (echo git missing & pause & exit /b 1)
  if not exist "%USERPROFILE%\CENTBOT_BACKUP" mkdir "%USERPROFILE%\CENTBOT_BACKUP"
  if exist config\local.yaml copy /Y config\local.yaml "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" >nul
  if exist data\eth.env copy /Y data\eth.env "%USERPROFILE%\CENTBOT_BACKUP\eth.env" >nul
  git fetch origin main
  git checkout -f main 2>nul
  git reset --hard origin/main
  git clean -fd
  if not exist config\local.yaml if exist "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" copy /Y "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" config\local.yaml >nul
  if not exist data\eth.env if exist "%USERPROFILE%\CENTBOT_BACKUP\eth.env" (
    if not exist data mkdir data
    copy /Y "%USERPROFILE%\CENTBOT_BACKUP\eth.env" data\eth.env >nul
  )
)

if errorlevel 1 (
  echo [CENTBOT] Sync failed
  pause
  exit /b 1
)

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"

echo.
echo [CENTBOT] Status:
"%PY%" -c "from centbot.windows.eth_key import signing_wallet_status; print('ETH:', signing_wallet_status().get('hint_lv'))" 2>nul
where docker >nul 2>&1 && docker info >nul 2>&1 && echo Docker: Engine Running || echo Docker: nav Ready ^(OK — restrictor^)

echo.
echo [CENTBOT] Ja ETH NAV: SET_ETH_KEY.bat ^(redzama ievade^), tad turpini.
set /p CONT=Turpinat FIX_LIVE / START? [Y/N]^> 
if /I not "!CONT!"=="Y" (
  echo Apturets. SET_ETH_KEY.bat → UPDATE_ALL.bat
  pause
  exit /b 0
)

call FIX_LIVE.bat
ENDLOCAL
exit /b %ERRORLEVEL%
