@echo off
REM Save ETH signing key so TaskMarket claims work after START.
REM Uses VISIBLE paste (getpass is broken in many Windows CMD sessions).
SETLOCAL EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "CENTBOT_ROOT=%CD%"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [CENTBOT] Python not found. Run SETUP.bat first.
  pause
  exit /b 1
)

"%PY%" -c "import eth_account" >nul 2>&1
if errorlevel 1 (
  echo [CENTBOT] Installing eth-account...
  "%PY%" -m pip install "eth-account>=0.11.0"
)

if not exist data mkdir data

echo.
echo === CENTBOT ETH signing key ===
echo Ielime MetaMask Private key ^(0x + 64 hex^).
echo NE seed frāzi. Publiskā adrese claimam NEPITIEk.
echo.

set "KEY="
set /p KEY=Private key^> 
if not defined KEY (
  echo [CENTBOT] Tukša ievade — nesaglabāju.
  pause
  exit /b 1
)

REM Strip accidental quotes
set "KEY=%KEY:"=%"

echo [CENTBOT] Saving to %CD%\data\eth.env + credentials.enc ...
"%PY%" -m centbot.windows.eth_key set --key "%KEY%"
set "EC=%ERRORLEVEL%"

if "%EC%"=="0" (
  if exist data\eth.env (
    echo [CENTBOT] OK — data\eth.env exists.
  ) else (
    echo [CENTBOT] WARNING: Python said OK but eth.env missing — writing fallback...
    > data\eth.env echo CENTBOT_ETH_PRIVATE_KEY=%KEY%
  )
  echo.
  echo [CENTBOT] Tagad: STOP.bat  tad  START.bat
  echo           Panelī: Parakstīšanas maks = IELĀDĒTS
) else (
  echo [CENTBOT] Nesaglabājās. Skaties kļūdu augstāk.
  echo           Pārliecinies ka atslēga ir 0x + tieši 64 hex simboli.
)

REM Clear key from this CMD session memory
set "KEY="
echo.
pause
ENDLOCAL
exit /b %EC%
