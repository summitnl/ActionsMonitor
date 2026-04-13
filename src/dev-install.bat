@echo off
title Actions Monitor — Setup
echo.
echo ========================================
echo   Actions Monitor — Install
echo ========================================
echo.

set "ROOT=%~dp0.."

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo         Download it from https://www.python.org/downloads/
    echo         Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Installing Python dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r "%~dp0requirements.txt"

if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [2/3] Setting up config...
if not exist "%ROOT%\config.yaml" (
    copy "%ROOT%\config.template.yaml" "%ROOT%\config.yaml" >nul
    echo        Created config.yaml from template. Add your workflows and GitHub token in that file.
) else (
    echo        config.yaml already exists, skipping.
)

echo.
echo [3/3] Done!
echo.
echo You can enable "Start with Windows" inside the app itself.
echo.
echo Starting Actions Monitor...
start "" pythonw "%~dp0main.py"
