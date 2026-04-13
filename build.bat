@echo off
:: Build Actions Monitor into a single .exe with embedded icon
:: Requires: pip install -r requirements.txt
setlocal

echo Generating app icon...
python -c "from main import _generate_app_ico; _generate_app_ico()"

echo Building .exe...
python -m PyInstaller --onefile --noconsole --name "ActionsMonitor" --icon=app.ico --add-data "config.template.yaml;." --distpath . --workpath build main.py

echo.
echo Done! Output: ActionsMonitor.exe
pause
