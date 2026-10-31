#!/usr/bin/env bash
# Build PyInstaller onedir and run headless UI smoke (sign-in page + icons + proxy routes).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
VER="$(grep '^VERSION' "$ROOT/admeasy_desktop/__init__.py" | sed 's/.*"\(.*\)".*/\1/')"
DIST="${ADMEASY_SMOKE_DIST:-/tmp/admeasy-frozen-smoke-dist}"
BUILD="${ADMEASY_SMOKE_BUILD:-/tmp/admeasy-frozen-smoke-build}"
HOME_DIR="${ADMEASY_HOME:-/tmp/admeasy-frozen-smoke-home}"
rm -rf "$DIST" "$BUILD" "$HOME_DIR"
mkdir -p "$HOME_DIR"
python3 -m pip install -q -U pip pyinstaller
python3 -m pip install -q -e "$ROOT"
export ADMEASY_RELEASE_VERSION="$VER"
python3 -m PyInstaller admeasy.spec --noconfirm --distpath "$DIST" --workpath "$BUILD"
BIN="$DIST/Admeasy/Admeasy"
test -x "$BIN"
export ADMEASY_HOME="$HOME_DIR"
export ADMEASY_HEADLESS_SMOKE=1
"$BIN" run
if [ -f "$HOME_DIR/logs/agent.log" ] && grep -qi traceback "$HOME_DIR/logs/agent.log"; then
  echo "traceback in agent.log:" >&2
  cat "$HOME_DIR/logs/agent.log" >&2
  exit 1
fi
echo "frozen UI smoke OK ($BIN)"
