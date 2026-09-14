@echo off
REM Windows: double-click this file to start the platform.
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Python was not found on this computer.
  echo Install it from https://www.python.org/downloads/
  echo Be sure to tick "Add python.exe to PATH" during installation.
  echo.
  pause
  exit /b 1
)

python run.py
echo.
echo Stopped.
pause
