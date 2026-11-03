@echo off
REM Verify Docker Desktop + pull CENTBOT sandbox image (python:3.12-slim)
SETLOCAL EnableExtensions
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [CENTBOT] Python not found. Run SETUP.bat first.
  exit /b 1
)

echo [CENTBOT] Checking Docker Desktop / pulling sandbox image...
where docker >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] docker.exe not on PATH.
  echo           Open Docker Desktop, wait until Engine is running, open a NEW CMD, retry.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Docker CLI found but daemon not running.
  echo           Start Docker Desktop and wait for "Engine running".
  exit /b 1
)

"%PY%" -m centbot.windows.docker_sandbox
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [CENTBOT] Docker sandbox OK. START.bat will use CENTBOT_REQUIRE_CONTAINER=1
) else (
  echo [CENTBOT] Docker sandbox not ready — see JSON above.
)
ENDLOCAL
exit /b %EC%
