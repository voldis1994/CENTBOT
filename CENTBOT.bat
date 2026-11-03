@echo off
REM Double-click entry: full LIVE system
cd /d "%~dp0"
if exist "%~dp0FULL_SYSTEM.bat" (
  call "%~dp0FULL_SYSTEM.bat"
) else if exist "%~dp0UPDATE_ALL.bat" (
  call "%~dp0UPDATE_ALL.bat"
) else (
  call "%~dp0START.bat"
)
exit /b %ERRORLEVEL%
