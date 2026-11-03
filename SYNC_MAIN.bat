@echo off
REM Force-sync to origin/main when untracked files block git pull.
REM KEEPS: config\local.yaml, data\, .venv\, certs\cacert.pem
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

where git >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] git missing — winget install Git.Git
  exit /b 1
)
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Not a git repo. Use CLONE_WINDOWS.bat
  exit /b 1
)

echo [CENTBOT] Backup config + data ...
if not exist "%USERPROFILE%\CENTBOT_BACKUP" mkdir "%USERPROFILE%\CENTBOT_BACKUP"
if exist config\local.yaml copy /Y config\local.yaml "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" >nul
if exist data\eth.env copy /Y data\eth.env "%USERPROFILE%\CENTBOT_BACKUP\eth.env" >nul
if exist data\basedagents-keypair.json copy /Y data\basedagents-keypair.json "%USERPROFILE%\CENTBOT_BACKUP\basedagents-keypair.json" >nul
if exist data\credentials.enc copy /Y data\credentials.enc "%USERPROFILE%\CENTBOT_BACKUP\credentials.enc" >nul

echo [CENTBOT] Fetch origin/main ...
git fetch origin main
if errorlevel 1 (
  echo [CENTBOT] fetch failed — internet / GitHub login
  exit /b 1
)

echo [CENTBOT] Hard reset to origin/main ^(fixes untracked overwrite errors^) ...
git checkout -f main 2>nul
git reset --hard origin/main
if errorlevel 1 (
  echo [CENTBOT] reset failed
  exit /b 1
)

REM Remove untracked files that blocked pull; do NOT use -x (would wipe ignored data/)
git clean -fd -e data -e .venv -e config/local.yaml -e certs/cacert.pem
git clean -fd

REM Restore operator secrets if somehow missing
if not exist config mkdir config
if not exist config\local.yaml if exist "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" (
  copy /Y "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" config\local.yaml >nul
  echo [CENTBOT] Restored config\local.yaml from backup
)
if not exist data mkdir data
if not exist data\eth.env if exist "%USERPROFILE%\CENTBOT_BACKUP\eth.env" copy /Y "%USERPROFILE%\CENTBOT_BACKUP\eth.env" data\eth.env >nul
if not exist data\basedagents-keypair.json if exist "%USERPROFILE%\CENTBOT_BACKUP\basedagents-keypair.json" copy /Y "%USERPROFILE%\CENTBOT_BACKUP\basedagents-keypair.json" data\basedagents-keypair.json >nul
if not exist data\credentials.enc if exist "%USERPROFILE%\CENTBOT_BACKUP\credentials.enc" copy /Y "%USERPROFILE%\CENTBOT_BACKUP\credentials.enc" data\credentials.enc >nul

echo [CENTBOT] Synced to:
git log -1 --oneline
echo [CENTBOT] config\local.yaml and data\ kept.
ENDLOCAL
exit /b 0
