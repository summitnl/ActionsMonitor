@echo off
title Actions Monitor — Uninstall
echo.
echo ========================================
echo   Actions Monitor — Uninstall
echo ========================================
echo.

:: Remove the "Start with Windows" registry entry if present
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ActionsMonitor" /f >nul 2>&1
if errorlevel 1 (
    echo [Startup]  No startup entry found (already removed or never set).
) else (
    echo [Startup]  Removed "Start with Windows" registry entry.
)

:: Uninstall Python packages
echo.
echo [Packages] Removing Python dependencies...
pip uninstall -y requests pyyaml Pillow pystray plyer >nul 2>&1
echo [Packages] Done.

echo.
echo Uninstall complete.
echo You can now delete this folder manually.
echo.
pause
