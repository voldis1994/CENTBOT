@echo off
REM ETH signing key for TaskMarket. Revolut public address is NOT a private key.
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
echo.
echo TaskMarket claimam vajag PRIVATE KEY:
echo   0x + 64 hex  =  66 simboli  ^(GARŠ^)
echo.
echo NEPAREIZI ^(tas ko biezi iedod Revolut^):
echo   0x + 40 hex  =  42 simboli  = publiska SANEMSANA adrese
echo.
echo Revolut Crypto parasti NEDOD private key.
echo Variants: MetaMask / Rabby → Account details → Show private key
echo BasedAgents strada BEZ ETH private key — START.bat pietiek.
echo.

set "KEY="
set /p KEY=Private key ^(vai payout adrese^)^> 
if not defined KEY (
  echo [CENTBOT] Tukša ievade — nesaglabāju.
  pause
  exit /b 1
)

set "KEY=%KEY:"=%"

echo [CENTBOT] Checking / saving ...
"%PY%" -m centbot.windows.eth_key set --key "%KEY%"
set "EC=%ERRORLEVEL%"

if "%EC%"=="0" (
  echo [CENTBOT] Private key SAGLABATS. STOP.bat + START.bat
) else (
  echo.
  echo [CENTBOT] Private key NESAGLABATS ^(skaties hint augstak^).
  echo           Ja ielimeji Revolut adresi — payout var but saglabats.
  echo           LIVE bez TaskMarket: START.bat  ^(BasedAgents^)
)

set "KEY="
echo.
pause
ENDLOCAL
exit /b %EC%
