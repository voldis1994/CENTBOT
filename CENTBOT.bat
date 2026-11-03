@echo off
REM Double-click: Python START by default (reliable). Set CENTBOT_USE_EXE=1 to force exe.
SETLOCAL EnableExtensions
cd /d "%~dp0"
call "%~dp0START.bat" %*
ENDLOCAL
exit /b %ERRORLEVEL%
