@echo off
:: Build Actions Monitor into a single .exe with embedded icon
:: Requires: pip install -r requirements.txt
setlocal

set "ROOT=%~dp0.."

echo Generating app icon...
python -c "import sys; sys.path.insert(0, '%~dp0'); from main import _generate_app_ico; _generate_app_ico()"

echo Building .exe...
python -m PyInstaller --onefile --noconsole --name "ActionsMonitor" --icon="%ROOT%\app.ico" --add-data "%ROOT%\config.template.yaml;." --distpath "%ROOT%" --workpath "%ROOT%\build" "%~dp0main.py"

echo.
echo Done! Output: %ROOT%\ActionsMonitor.exe
pause
