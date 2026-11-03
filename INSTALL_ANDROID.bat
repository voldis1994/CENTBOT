@echo off
REM Install Android SDK + CENTBOT_ANDROID_01..N AVDs for the emulator lane.
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
echo [CENTBOT] Android SDK install / AVD setup
echo          This may install Android Studio via winget ^(long download^).
echo.

"%PY%" -m centbot.windows.android_sdk -y
set "EC=%ERRORLEVEL%"

REM Persist common SDK path for future CMD sessions
if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
  setx ANDROID_HOME "%LOCALAPPDATA%\Android\Sdk" >nul
  setx ANDROID_SDK_ROOT "%LOCALAPPDATA%\Android\Sdk" >nul
  echo [CENTBOT] Set ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk
)

if "%EC%"=="0" (
  echo.
  echo [CENTBOT] Android OK. Run STOP.bat then START.bat
  echo          Panel should show Android ON with AVD slots, not "nav SDK".
) else (
  echo.
  echo [CENTBOT] Android not ready yet.
  echo          1^) Install Android Studio manually if winget failed
  echo          2^) Open SDK Manager → install Platform-Tools + Emulator + Android 30 system image
  echo          3^) Re-run INSTALL_ANDROID.bat
)
ENDLOCAL
exit /b %EC%
