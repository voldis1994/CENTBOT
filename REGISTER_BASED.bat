@echo off
REM Register BasedAgents AgentSig identity (fixes basedagents_identity_missing)
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

echo [CENTBOT] Registering BasedAgents identity...
"%PY%" -m centbot.windows.register_based --name CENTBOT
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [CENTBOT] OK. Run STOP.bat then START.bat
) else (
  echo [CENTBOT] Register failed — check network / api.basedagents.ai
)
ENDLOCAL
exit /b %EC%
