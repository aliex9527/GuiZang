@echo off
rem ============================================================
rem  GuiZang workspace setup (Windows)
rem  ASCII only on purpose: cmd parses .bat with the OEM codepage,
rem  non-ASCII text here would garble and can break commands.
rem ============================================================
setlocal
cd /d "%~dp0"
set "MIRROR=https://mirrors.aliyun.com/pypi/simple"

echo ============================================================
echo   GuiZang workspace setup
echo ============================================================
echo.

set "PY="
py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3.10+ not found.
  echo         Download: https://www.python.org/downloads/
  echo         During install, tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)
echo Using interpreter: %PY%
%PY% --version

echo.
echo [1/3] Creating virtual env .venv
if exist ".venv\Scripts\python.exe" (
  echo       already exists, skip
) else (
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] failed to create venv
    pause
    exit /b 1
  )
)

echo.
echo [2/3] Installing dependencies (aliyun mirror)
".venv\Scripts\python.exe" -m pip install --upgrade pip -i %MIRROR% --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i %MIRROR%
if errorlevel 1 (
  echo       mirror failed, retry with the official index...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] dependency install failed
    pause
    exit /b 1
  )
)

echo.
echo [3/3] Generating icons
".venv\Scripts\python.exe" tools\make_icon.py

echo.
echo Done. Double-click run.bat to start.
pause
