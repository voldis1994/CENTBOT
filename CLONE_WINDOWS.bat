@echo off
REM One-shot: clone GitHub CENTBOT to C:\CENTBOT, keep config from CENTBOT-main / backup
SETLOCAL EnableExtensions

echo ============================================
echo  CENTBOT — clone from GitHub + keep config
echo ============================================

where git >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Installing Git via winget...
  winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
  echo [CENTBOT] Close this window, open a NEW cmd, re-run CLONE_WINDOWS.bat
  pause
  exit /b 1
)

REM Backup config from common ZIP / old folders
mkdir C:\CENTBOT_BACKUP 2>nul
for %%D in (C:\CENTBOT-main C:\CENTBOT) do (
  if exist "%%D\config\local.yaml" copy /Y "%%D\config\local.yaml" C:\CENTBOT_BACKUP\local.yaml >nul
  if exist "%%D\data" xcopy /E /I /Y "%%D\data" C:\CENTBOT_BACKUP\data\ >nul
)

if exist C:\CENTBOT (
  echo [CENTBOT] Removing old C:\CENTBOT ^(config already backed up^)...
  rmdir /S /Q C:\CENTBOT
)

echo [CENTBOT] Cloning https://github.com/voldis1994/CENTBOT ...
git clone https://github.com/voldis1994/CENTBOT.git C:\CENTBOT
if errorlevel 1 (
  echo [CENTBOT] git clone failed
  pause
  exit /b 1
)

cd /d C:\CENTBOT
git checkout main
git pull origin main

mkdir config 2>nul
mkdir data 2>nul
mkdir certs 2>nul
if exist C:\CENTBOT_BACKUP\local.yaml copy /Y C:\CENTBOT_BACKUP\local.yaml C:\CENTBOT\config\local.yaml
if exist C:\CENTBOT_BACKUP\data xcopy /E /I /Y C:\CENTBOT_BACKUP\data C:\CENTBOT\data\
if exist centbot\certs\cacert.pem copy /Y centbot\certs\cacert.pem certs\cacert.pem >nul

echo [CENTBOT] Installing deps ^(SETUP^)...
call SETUP.bat

echo.
echo [CENTBOT] DONE.
echo   Folder:  C:\CENTBOT   ^(git connected to GitHub^)
echo   Config:  C:\CENTBOT\config\local.yaml
echo   Next:    STOP.bat then START.bat
echo   Update:  cd /d C:\CENTBOT ^&^& git pull origin main
echo.
pause
ENDLOCAL
exit /b 0
