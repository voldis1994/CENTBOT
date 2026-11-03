@echo off
REM Build CENTBOT.exe with PyInstaller (run on Windows after SETUP.bat)
SETLOCAL EnableExtensions
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY set "PY=python"

echo [CENTBOT] Building CENTBOT.exe ...
"%PY%" -m pip install -U pip pyinstaller certifi
if errorlevel 1 (
  echo [CENTBOT] Failed to install PyInstaller
  pause
  exit /b 1
)

REM Ensure vendored CA bundle exists before packaging
if not exist "centbot\certs\cacert.pem" (
  echo [CENTBOT] Seeding centbot\certs\cacert.pem from certifi...
  "%PY%" -c "import certifi,shutil,pathlib; p=pathlib.Path('centbot/certs'); p.mkdir(parents=True, exist_ok=True); shutil.copy(certifi.where(), p/'cacert.pem'); print('ok', (p/'cacert.pem').stat().st_size)"
)

"%PY%" -m PyInstaller --noconfirm --clean centbot.spec
if errorlevel 1 (
  echo [CENTBOT] PyInstaller failed
  pause
  exit /b 1
)

if exist "dist\CENTBOT.exe" (
  copy /Y "dist\CENTBOT.exe" "CENTBOT.exe" >nul
  if not exist "certs" mkdir certs
  copy /Y "centbot\certs\cacert.pem" "certs\cacert.pem" >nul
  echo [CENTBOT] OK — CENTBOT.exe is ready in this folder.
  echo           TLS CA: certs\cacert.pem ^(also used next to the exe^)
  echo           Double-click CENTBOT.exe or CENTBOT.bat to start LIVE.
) else (
  echo [CENTBOT] dist\CENTBOT.exe missing
  pause
  exit /b 1
)
echo.
pause
ENDLOCAL
exit /b 0
