@echo off
REM Start Docker Desktop if needed, wait for Engine, pull sandbox image.
REM NEVER blocks CENTBOT forever — on failure writes restrictor fallback and can START.
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [CENTBOT] Python not found. Run SETUP.bat first.
  pause
  exit /b 1
)

if not exist data mkdir data

echo.
echo === CENTBOT Docker sandbox ===
echo 1^) Start Docker Desktop  2^) Wait Engine  3^) Pull python:3.12-slim  4^) Smoke test
echo.

REM Put common Docker CLI on PATH for this session
if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" (
  set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
)
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  echo [CENTBOT] Launching Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
)

echo [CENTBOT] Waiting for Docker Engine ^(up to ~2 min^)...
set "READY=0"
for /L %%I in (1,1,24) do (
  docker info >nul 2>&1
  if not errorlevel 1 (
    set "READY=1"
    echo [CENTBOT] Engine Running.
    goto engine_ok
  )
  echo         ... still starting %%I/24
  timeout /t 5 /nobreak >nul
)
:engine_ok

if "%READY%"=="0" (
  echo [CENTBOT] Engine vēl nav Ready.
  echo           Atver Docker Desktop manuāli, pagaidi zaļo ikonu, tad šo bat vēlreiz.
  echo           LIVE tikmēr strādā ar restrictor — START.bat joprojām OK.
  > data\docker.env echo CENTBOT_REQUIRE_CONTAINER=0
  >> data\docker.env echo CENTBOT_SANDBOX_BACKEND=restrictor_only
  >> data\docker.env echo CENTBOT_SANDBOX_IMAGE=python:3.12-slim
  echo.
  set /p DOSTART=Palaist START.bat tagad? [Y/N]^> 
  if /I "!DOSTART!"=="Y" call START.bat
  goto end_fail
)

"%PY%" -m centbot.windows.docker_sandbox --soft
set "EC=%ERRORLEVEL%"

if exist data\docker.env (
  findstr /C:"CENTBOT_REQUIRE_CONTAINER=1" data\docker.env >nul
  if not errorlevel 1 (
    echo [CENTBOT] Docker sandbox READY.
  ) else (
    echo [CENTBOT] Docker soft-fallback — CENTBOT START joprojām strādā.
  )
)

echo.
set /p DOSTART=Palaist START.bat tagad? [Y/N]^> 
if /I "!DOSTART!"=="Y" call START.bat
:end_ok
echo.
pause
ENDLOCAL
exit /b 0

:end_fail
echo.
pause
ENDLOCAL
exit /b 0
