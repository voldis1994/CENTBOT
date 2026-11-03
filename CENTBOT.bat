@echo off
REM Double-click launcher — prefers CENTBOT.exe, else START.bat
SETLOCAL EnableExtensions
cd /d "%~dp0"

if exist "%~dp0CENTBOT.exe" (
  echo [CENTBOT] Starting CENTBOT.exe ...
  start "CENTBOT" "%~dp0CENTBOT.exe" %*
  exit /b 0
)
if exist "%~dp0dist\CENTBOT.exe" (
  echo [CENTBOT] Starting dist\CENTBOT.exe ...
  start "CENTBOT" "%~dp0dist\CENTBOT.exe" %*
  exit /b 0
)

echo [CENTBOT] CENTBOT.exe not built yet. Using START.bat
echo           To build exe: run BUILD_EXE.bat once
call "%~dp0START.bat" %*
ENDLOCAL
exit /b %ERRORLEVEL%
