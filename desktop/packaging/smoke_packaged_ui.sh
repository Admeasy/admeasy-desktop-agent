#!/usr/bin/env bash
# Build linux onedir bundle and verify the loopback UI serves HTML + JS with correct MIME types.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
VER="$(grep '^VERSION' "$ROOT/admeasy_desktop/__init__.py" | sed 's/.*"\(.*\)".*/\1/')"
rm -rf /tmp/admeasy-smoke-dist /tmp/admeasy-smoke-build
python3 -m venv /tmp/admeasy-smoke-venv
/tmp/admeasy-smoke-venv/bin/pip install -q -U pip pyinstaller
/tmp/admeasy-smoke-venv/bin/pip install -q -e "$ROOT"
export ADMEASY_RELEASE_VERSION="$VER"
/tmp/admeasy-smoke-venv/bin/python -m PyInstaller admeasy.spec --noconfirm \
  --distpath /tmp/admeasy-smoke-dist --workpath /tmp/admeasy-smoke-build
export ADMEASY_HOME=/tmp/admeasy-smoke-home
mkdir -p "$ADMEASY_HOME"
/tmp/admeasy-smoke-venv/bin/pip install -q pytest
/tmp/admeasy-smoke-venv/bin/python -m pytest "$ROOT/tests/test_packaged_ui.py" -q --no-header
echo "packaged UI smoke OK"
