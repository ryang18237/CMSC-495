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

echo.
echo Starting SkillbridgeAI.
echo.
echo First run on this computer takes a few minutes: it sets up the
echo environment and offers to install Ollama, which runs the language
echo model locally. Press Return at the prompt to accept.
echo.

python run.py
echo.
echo Stopped.
pause
