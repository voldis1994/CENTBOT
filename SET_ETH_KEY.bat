@echo off
REM Store ETH signing private key for TaskMarket / BountyBook live claims.
REM Public payout address alone is NOT enough — claims need EIP-191 signatures.
SETLOCAL EnableExtensions
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [CENTBOT] Python not found. Run SETUP.bat first.
  exit /b 1
)

echo.
echo === CENTBOT ETH signing key ===
echo TaskMarket/BountyBook claim fails with wallet_required without this.
echo Enter a single hex private key ^(0x...^). NEVER enter a seed/mnemonic.
echo Public receive address from the wizard is for payouts only.
echo.

"%PY%" -m centbot.windows.eth_key set
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo.
  echo [CENTBOT] Key saved. Run STOP.bat then START.bat to reload.
) else (
  echo [CENTBOT] Key not saved. See message above.
)
ENDLOCAL
exit /b %EC%
