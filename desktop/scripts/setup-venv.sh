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
  pip install 'pyobjc-framework-Quartz>=10' 'pyobjc-framework-ApplicationServices>=10' || true
fi
echo ""
echo "Done. Activate with: source desktop/.venv/bin/activate"
echo "Set backend: export ADMEASY_BACKEND=https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"
echo "Then: python -m admeasy_desktop doctor && python -m admeasy_desktop run"
