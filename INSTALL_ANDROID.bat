@echo off
REM Install Android SDK (Google cmdline-tools) + CENTBOT_ANDROID AVDs.
REM Does NOT require Android Studio, but can fall back to winget Studio.
SETLOCAL EnableExtensions EnableDelayedExpansion
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
echo ============================================
echo  CENTBOT Android SDK + AVD setup
echo  1^) Google cmdline-tools  2^) platform-tools/emulator
echo  3^) system-image android-30  4^) CENTBOT_ANDROID_01..N
echo ============================================
echo.

"%PY%" -m centbot.windows.android_sdk -y
set "EC=%ERRORLEVEL%"

if exist "%LOCALAPPDATA%\Android\Sdk" (
  setx ANDROID_HOME "%LOCALAPPDATA%\Android\Sdk" >nul
  setx ANDROID_SDK_ROOT "%LOCALAPPDATA%\Android\Sdk" >nul
  set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
  set "ANDROID_SDK_ROOT=%LOCALAPPDATA%\Android\Sdk"
  set "PATH=%LOCALAPPDATA%\Android\Sdk\platform-tools;%LOCALAPPDATA%\Android\Sdk\emulator;%LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest\bin;%PATH%"
  echo [CENTBOT] ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk
)

if exist data\android.env (
  echo [CENTBOT] Wrote data\android.env for START.bat
)

if "%EC%"=="0" (
  echo.
  echo [CENTBOT] Android OK.
  echo          Next: STOP.bat then START.bat
  echo          Panel Android should show AVD slots ^(not "nav SDK"^).
) else (
  echo.
  echo [CENTBOT] Android not fully ready ^(exit %EC%^).
  echo          Re-run INSTALL_ANDROID.bat as Administrator.
  echo          Or install Android Studio, open SDK Manager once, then re-run.
)
ENDLOCAL
exit /b %EC%
