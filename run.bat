@echo off
rem Start GuiZang from source (Windows). Run setup.bat first.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo [ERROR] .venv not found. Double-click setup.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
