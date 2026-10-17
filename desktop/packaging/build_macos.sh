#!/bin/bash
# Build, sign, notarize and package Admeasy.dmg. Run on a Mac.
# Needs: Python 3.11+, an Apple Developer ID Application certificate, and a notarytool keychain profile:
#   xcrun notarytool store-credentials admeasy-notary --apple-id you@x.com --team-id TEAMID --password <app-specific-password>
# SIGN_ID="Developer ID Application: Your Name (TEAMID)"
set -euo pipefail
cd "$(dirname "$0")"
: "${SIGN_ID:?set SIGN_ID to your Developer ID Application identity}"
python3 -m venv .build && source .build/bin/activate
pip install -q -r ../requirements.txt
python -m PyInstaller admeasy.spec --noconfirm --distpath dist --workpath build
APP=dist/Admeasy.app
# Sign with the SAME identity every release: macOS ties Screen Recording / Accessibility grants to the signature.
codesign --force --deep --options runtime --timestamp --entitlements entitlements.plist --sign "$SIGN_ID" "$APP"
codesign --verify --deep --strict "$APP"
rm -f Admeasy.dmg
hdiutil create -volname Admeasy -srcfolder "$APP" -ov -format UDZO Admeasy.dmg   # or: create-dmg for the drag-to-Applications layout
codesign --sign "$SIGN_ID" --timestamp Admeasy.dmg
xcrun notarytool submit Admeasy.dmg --keychain-profile admeasy-notary --wait
xcrun stapler staple Admeasy.dmg
echo "built: $(pwd)/Admeasy.dmg"
