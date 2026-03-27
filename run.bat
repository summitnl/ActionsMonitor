@echo off
:: Launch Actions Monitor without a console window
:: Uses pythonw.exe so no terminal flickers up on startup
setlocal
set "SCRIPT=%~dp0main.py"

:: Prefer pythonw (no console) over python
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%SCRIPT%"
) else (
    start "" python "%SCRIPT%"
)
