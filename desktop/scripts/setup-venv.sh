#!/usr/bin/env bash
# Create a virtual environment and install the desktop agent (macOS / Linux).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
if ! "$PY" -m venv .venv 2>/dev/null; then
  echo "python venv failed. On Debian/Ubuntu: sudo apt install python3-venv" >&2
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
pip install -e .
if [[ "$(uname -s)" == "Darwin" ]]; then
  pip install 'pyobjc-framework-Quartz>=10' 'pyobjc-framework-ApplicationServices>=10' 'pyobjc-framework-Cocoa>=10' || true
  echo ""
  echo "macOS: pink agent cursor uses AppKit (pyobjc-framework-Cocoa), not Tk."
  echo "Grant Accessibility to Terminal (or your IDE) in System Settings for CUA clicks."
elif [[ "$(uname -s)" == "Linux" ]]; then
  if ! "$PY" -c "import _tkinter" 2>/dev/null; then
    echo ""
    echo "Linux: install Tk for the pink agent cursor, e.g. sudo apt install python3-tk"
    echo "Or disable overlay: export ADMEASY_SHOW_AGENT_CURSOR=0"
  fi
fi
echo ""
echo "Done. From this directory: source .venv/bin/activate"
echo "Set backend: export ADMEASY_BACKEND=https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"
echo "Then: python -m admeasy_desktop doctor && python -m admeasy_desktop run"
