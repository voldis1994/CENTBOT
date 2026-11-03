@echo off
REM CENTBOT Windows SETUP — resumable official-component installer
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  CENTBOT SETUP
echo  Official sources only. Resumable progress.
echo ============================================
echo.

REM --- Bootstrap Python automatically via winget if missing ---
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [CENTBOT] Python missing — installing Python 3.12 via winget ^(official^)...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo [CENTBOT] winget not found. Install App Installer from Microsoft Store, then re-run SETUP.bat
    pause
    exit /b 1
  )
  winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo [CENTBOT] winget Python install failed. Trying Python.Python.3.11...
    winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
  )
  REM Refresh PATH for this session
  set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%PATH%"
  where py >nul 2>&1 && set "PY=py -3"
  if not defined PY (
    where python >nul 2>&1 && set "PY=python"
  )
)
if not defined PY (
  echo [CENTBOT] Python still not on PATH after install. Open a NEW terminal and re-run SETUP.bat
  pause
  exit /b 1
)

echo [CENTBOT] Using: %PY%
%PY% --version

if not exist data mkdir data
if not exist data\setup mkdir data\setup
if not exist logs mkdir logs

echo [CENTBOT] Running hardware check + component install ^(assume-yes for missing packages^)...
%PY% -m centbot.windows.setup --yes %*
set "EC=%ERRORLEVEL%"

echo.
echo [CENTBOT] First-run / update configuration wizard ^(strict validation^)...
%PY% -m centbot.windows.wizard
if errorlevel 1 (
  echo [CENTBOT] Wizard FAILED — config/local.yaml was NOT written with invalid data.
  echo           Fix inputs and re-run: %PY% -m centbot.windows.wizard
  set "EC=1"
)

echo.
if "%EC%"=="0" (
  echo [CENTBOT] SETUP finished. Next: START.bat
) else (
  echo [CENTBOT] SETUP finished with issues ^(exit %EC%^). Re-run SETUP.bat to resume.
)
echo.
pause
ENDLOCAL
exit /b %EC%
