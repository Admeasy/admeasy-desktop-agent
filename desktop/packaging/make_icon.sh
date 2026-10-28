#!/usr/bin/env bash
# Build Admeasy.icns from admeasy.ai artwork (run on macOS before PyInstaller).
set -euo pipefail
cd "$(dirname "$0")"
SRC="${1:-https://admeasy.ai/apple-touch-icon.png}"
PNG="icon.png"
ICNS="icon.icns"
curl -fsSL "$SRC" -o "$PNG"
rm -rf icon.iconset
mkdir -p icon.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$PNG" --out "icon.iconset/icon_${size}x${size}.png" >/dev/null
  dbl=$((size * 2))
  sips -z "$dbl" "$dbl" "$PNG" --out "icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns icon.iconset -o "$ICNS"
echo "wrote $(pwd)/$ICNS"
