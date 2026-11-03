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

echo [CENTBOT] Bootstrap interpreter: %PY%
%PY% --version
if errorlevel 1 (
  echo [CENTBOT] Python failed to start. Re-install Python and tick "Add to PATH".
  pause
  exit /b 1
)

if not exist data mkdir data
if not exist data\setup mkdir data\setup
if not exist logs mkdir logs

REM --- Create project venv early (so deps are isolated and always found) ---
if not exist ".venv\Scripts\python.exe" (
  echo [CENTBOT] Creating .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [CENTBOT] venv create failed — will install packages into the system Python instead.
  )
)
if exist ".venv\Scripts\python.exe" (
  set "PY=%CD%\.venv\Scripts\python.exe"
  echo [CENTBOT] Using venv: %PY%
)

REM --- CRITICAL: install deps BEFORE any "python -m centbot..." import (needs PyYAML) ---
echo [CENTBOT] Installing Python packages from requirements.txt ...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [CENTBOT] pip upgrade failed — continuing with existing pip
)
"%PY%" -m pip install -r "%CD%\requirements.txt"
if errorlevel 1 (
  echo [CENTBOT] Full requirements install failed — installing minimum bootstrap ^(PyYAML^)...
  "%PY%" -m pip install "pyyaml>=6.0.1" "requests>=2.31.0" "flask>=3.0.0" "psutil>=5.9.8"
  if errorlevel 1 (
    echo [CENTBOT] CRITICAL: cannot install PyYAML. Check network / pip, then re-run SETUP.bat
    pause
    exit /b 1
  )
)

"%PY%" -c "import yaml, requests, flask; print('[CENTBOT] Core imports OK')"
if errorlevel 1 (
  echo [CENTBOT] CRITICAL: yaml/requests/flask still missing after pip. Re-run SETUP.bat
  pause
  exit /b 1
)

echo [CENTBOT] Running hardware check + component install ^(assume-yes for missing packages^)...
"%PY%" -m centbot.windows.setup --yes %*
set "EC=%ERRORLEVEL%"

echo.
echo [CENTBOT] First-run / update configuration wizard ^(strict validation^)...
"%PY%" -m centbot.windows.wizard
if errorlevel 1 (
  echo [CENTBOT] Wizard FAILED — config/local.yaml was NOT written with invalid data.
  echo           Fix inputs and re-run: "%PY%" -m centbot.windows.wizard
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
