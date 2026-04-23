#!/usr/bin/env bash
# Build Actions Monitor into a single Linux binary
# Requires: pip install -r requirements.txt pyinstaller
#
# Run directly on Linux, or from Windows via WSL:
#   wsl -d Ubuntu-24.04 -- bash src/build.sh
#
# Prerequisites (Ubuntu 24.04):
#   sudo apt-get install -y python3-pip python3-tk python3-venv \
#       gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
#   pip3 install --break-system-packages -r src/requirements.txt pyinstaller
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# When invoked via WSL on a /mnt/c path, copy to /tmp to avoid
# Windows-filesystem permission issues with PyInstaller.
if [[ "$ROOT" == /mnt/* ]]; then
    WORK="/tmp/am-build-$$"
    echo "Detected Windows filesystem — copying to $WORK ..."
    cp -r "$ROOT" "$WORK"
    trap 'rm -rf "$WORK"' EXIT

    cd "$WORK"
    SCRIPT_DIR="$WORK/src"
    OUT_DIR="$ROOT"
else
    cd "$ROOT"
    OUT_DIR="$ROOT"
fi

echo "Generating app icon..."
(cd src && python3 -c "from main import _generate_app_ico; _generate_app_ico()")

echo "Building Linux binary..."
python3 -m PyInstaller --onefile --windowed \
    --name "ActionsMonitor-linux" \
    --icon "app.ico" \
    --add-data "config.template.yaml:." \
    --distpath dist \
    --workpath build \
    src/main.py

cp dist/ActionsMonitor-linux "$OUT_DIR/"
echo ""
echo "Done! Output: $OUT_DIR/ActionsMonitor-linux"
