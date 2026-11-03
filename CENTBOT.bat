@echo off
REM Always FIX path: never relaunch broken CENTBOT.exe
SETLOCAL
cd /d "%~dp0"
if exist FIX_NOW.bat (
  call FIX_NOW.bat
) else (
  call STOP.bat
  call START.bat
)
ENDLOCAL
exit /b %ERRORLEVEL%
