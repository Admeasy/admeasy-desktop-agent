#!/usr/bin/env bash
# macOS release DMG: signed+notarized when SIGN_ID is set, otherwise ad-hoc signed (Right-click > Open once).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
VER="$(grep '^VERSION' "$ROOT/admeasy_desktop/__init__.py" | sed 's/.*"\(.*\)".*/\1/')"
SIGNED="${SIGN_ID:-}"
OUT_UNSIGNED="Admeasy-${VER}-macos-unsigned.dmg"
OUT_SIGNED="Admeasy-${VER}-macos.dmg"

rm -rf .build dist build dmg_staging
python3 -m venv .build
source .build/bin/activate
pip install -q -U pip wheel
pip install -q -r "$ROOT/requirements.txt" pyinstaller
pip install -q 'pyobjc-framework-Quartz>=10' 'pyobjc-framework-ApplicationServices>=10' || true
export ADMEASY_RELEASE_VERSION="$VER"
bash make_icon.sh 2>/dev/null || true
python -m PyInstaller admeasy.spec --noconfirm --distpath dist --workpath build
APP=dist/Admeasy.app

if [[ -n "$SIGNED" ]]; then
  codesign --force --options runtime --timestamp --entitlements entitlements.plist --sign "$SIGN_ID" "$APP"
  codesign --verify --deep --strict "$APP"
else
  codesign --force --options runtime --entitlements entitlements.plist --sign - "$APP"
fi

rm -rf dmg_staging
mkdir -p dmg_staging
cp -R "$APP" dmg_staging/
ln -sf /Applications dmg_staging/Applications
STAGING_DMG="Admeasy-staging.dmg"
rm -f "$STAGING_DMG"
hdiutil create -volname "Admeasy" -srcfolder dmg_staging -ov -format UDZO "$STAGING_DMG"

if [[ -n "$SIGNED" ]]; then
  rm -f "$OUT_SIGNED"
  cp "$STAGING_DMG" "$OUT_SIGNED"
  codesign --sign "$SIGN_ID" --timestamp "$OUT_SIGNED"
  xcrun notarytool submit "$OUT_SIGNED" --keychain-profile admeasy-notary --wait
  xcrun stapler staple "$OUT_SIGNED"
  echo "built signed: $(pwd)/$OUT_SIGNED"
else
  rm -f "$OUT_UNSIGNED"
  mv "$STAGING_DMG" "$OUT_UNSIGNED"
  echo "built unsigned: $(pwd)/$OUT_UNSIGNED"
fi
