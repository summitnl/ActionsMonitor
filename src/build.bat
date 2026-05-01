@echo off
:: Build Actions Monitor as a folder distribution and zip it.
:: Requires: pip install -r requirements.txt
setlocal

set "ROOT=%~dp0.."
set "SRC=%~dp0"

echo Generating app icon...
cd /d "%SRC%"
python -c "from main import _generate_app_ico; _generate_app_ico()"
cd /d "%ROOT%"

echo Building dist folder...
python -m PyInstaller --onedir --noconsole --name "ActionsMonitor" --icon="%ROOT%\app.ico" --add-data "%ROOT%\config.template.yaml;." --distpath "%ROOT%\dist" --workpath "%ROOT%\build" "%SRC%main.py"

if errorlevel 1 (
  echo.
  echo Build failed.
  exit /b 1
)

echo Zipping dist...
:: Wrap in top-level "ActionsMonitor/" so the zip layout matches what
:: winget NestedInstallerFiles + Scoop extract_dir expect. Use Python's
:: zipfile rather than PowerShell's Compress-Archive — the latter relies on
:: a module that isn't autoloaded under constrained / non-interactive PS hosts.
python -c "import shutil; shutil.make_archive(r'%ROOT%\ActionsMonitor', 'zip', r'%ROOT%\dist', 'ActionsMonitor')"

echo.
echo Done!
echo   Folder: %ROOT%\dist\ActionsMonitor
echo   Zip:    %ROOT%\ActionsMonitor.zip
pause
