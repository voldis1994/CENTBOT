@echo off
REM Quick health: ETH / Docker / Android / config — never starts engine
SETLOCAL EnableExtensions
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"

echo.
echo === CENTBOT STATUS ===
echo Root: %CD%
if exist config\local.yaml (echo Config: OK config\local.yaml) else (echo Config: TRUKST — SETUP.bat)
if exist data\eth.env (echo eth.env: OK) else (echo eth.env: NAV — SET_ETH_KEY.bat)
if exist data\basedagents-keypair.json (echo BasedAgents keypair: OK) else (echo BasedAgents keypair: NAV — REGISTER_BASED.bat)
if exist data\docker.env (echo docker.env:) else (echo docker.env: NAV)
if exist data\docker.env type data\docker.env
where docker >nul 2>&1 && (docker info >nul 2>&1 && echo Docker Engine: Running || echo Docker Engine: NOT running) || echo Docker CLI: not on PATH
if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (echo Android SDK: OK) else (echo Android SDK: NAV — INSTALL_ANDROID.bat)

echo.
"%PY%" -m centbot.windows.eth_key status 2>nul
"%PY%" -m centbot.windows.docker_sandbox --status 2>nul
echo.
pause
ENDLOCAL
exit /b 0
