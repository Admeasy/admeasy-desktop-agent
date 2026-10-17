#!/usr/bin/env bash
# Build an unsigned Admeasy.dmg (beta). Ad-hoc signs the .app so macOS will run it after Right-click > Open.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
VER="$(grep '^VERSION' "$ROOT/admeasy_desktop/__init__.py" | sed 's/.*"\(.*\)".*/\1/')"
rm -rf .build dist build dmg_staging
python3 -m venv .build
source .build/bin/activate
pip install -q -U pip wheel
pip install -q -r "$ROOT/requirements.txt" pyinstaller
pip install -q 'pyobjc-framework-Quartz>=10' 'pyobjc-framework-ApplicationServices>=10' || true
export ADMEASY_RELEASE_VERSION="$VER"
python -m PyInstaller admeasy.spec --noconfirm --distpath dist --workpath build
APP=dist/Admeasy.app
codesign --force --deep -s - "$APP" || true
rm -rf dmg_staging
mkdir -p dmg_staging
cp -R "$APP" dmg_staging/
ln -sf /Applications dmg_staging/Applications
rm -f Admeasy-unsigned.dmg
hdiutil create -volname "Admeasy" -srcfolder dmg_staging -ov -format UDZO "Admeasy-${VER}-macos-unsigned.dmg"
echo "built: $(pwd)/Admeasy-${VER}-macos-unsigned.dmg"
