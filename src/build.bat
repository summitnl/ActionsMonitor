@echo off
:: Build Actions Monitor into a single .exe with embedded icon
:: Requires: pip install -r requirements.txt
setlocal

set "ROOT=%~dp0.."
set "SRC=%~dp0"

echo Generating app icon...
cd /d "%SRC%"
python -c "from main import _generate_app_ico; _generate_app_ico()"
cd /d "%ROOT%"

echo Building .exe...
python -m PyInstaller --onefile --noconsole --name "ActionsMonitor" --icon="%ROOT%\app.ico" --add-data "%ROOT%\config.template.yaml;." --distpath "%ROOT%" --workpath "%ROOT%\build" "%SRC%main.py"

echo.
echo Done! Output: %ROOT%\ActionsMonitor.exe
pause
