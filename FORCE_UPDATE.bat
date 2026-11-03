@echo off
REM Paste-friendly: run this NOW if git pull says untracked files would be overwritten.
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo [CENTBOT] FORCE_UPDATE — backup config/data, reset to origin/main, clean untracked
if not exist "%USERPROFILE%\CENTBOT_BACKUP" mkdir "%USERPROFILE%\CENTBOT_BACKUP"
if exist config\local.yaml copy /Y config\local.yaml "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" >nul
if exist data (
  xcopy /E /I /Y data "%USERPROFILE%\CENTBOT_BACKUP\data" >nul
)

git fetch origin main
git checkout -f main
git reset --hard origin/main
git clean -fd

if not exist config\local.yaml if exist "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" (
  if not exist config mkdir config
  copy /Y "%USERPROFILE%\CENTBOT_BACKUP\local.yaml" config\local.yaml >nul
)
if exist "%USERPROFILE%\CENTBOT_BACKUP\data" (
  if not exist data mkdir data
  xcopy /E /I /Y "%USERPROFILE%\CENTBOT_BACKUP\data" data >nul
)

echo [CENTBOT] Done:
git log -1 --oneline
echo.
echo Next: SET_ETH_KEY.bat   then   START.bat
echo Or:   UPDATE_ALL.bat
pause
ENDLOCAL
exit /b 0
