#!/usr/bin/env bash
# Install the Admeasy helper for developers / power users.
#
# Normal users should download the .dmg from GitHub Releases and drag Admeasy to
# Applications (see docs/INSTALL_BETA.md). This script is for pairing another machine
# from Connections → copy install command.
set -euo pipefail

PAIR="${ADMEASY_PAIR:-}"
BACKEND="${ADMEASY_BACKEND:-https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com}"
REPO="${ADMEASY_REPO:-https://github.com/Admeasy/admeasy-desktop-agent.git}"
SRC="${ADMEASY_SOURCE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pair) PAIR="${2:-}"; shift 2 ;;
    --backend) BACKEND="${2:-}"; shift 2 ;;
    --source) SRC="${2:-}"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Admeasy helper install (terminal)

Most people should NOT run this. Download the macOS .dmg or Windows .exe from:
  https://github.com/Admeasy/admeasy-desktop-agent/releases

usage: install.sh [--pair CODE] [--backend URL] [--source DIR]
EOF
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

pick_python() {
  for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

if ! PY_BOOT=$(pick_python); then
  ver="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown)"
  cat >&2 <<EOF
ERROR: Python 3.11+ is required (this Mac has ${ver}).

Easiest fix: download Admeasy from GitHub Releases (no Python needed):
  https://github.com/Admeasy/admeasy-desktop-agent/releases

Or install Python 3.12:
  brew install python@3.12
  # then re-run this script
EOF
  exit 1
fi

ROOT="$HOME/.admeasy/src"
if [[ -n "$SRC" ]]; then
  ROOT="$SRC"
elif [[ ! -d "$ROOT/.git" ]]; then
  mkdir -p "$(dirname "$ROOT")"
  git clone --depth 1 "$REPO" "$ROOT"
else
  git -C "$ROOT" pull --ff-only
fi

VENV="$HOME/.admeasy/venv"
"$PY_BOOT" -m venv "$VENV"
PY="$VENV/bin/python"
"$PY" -m pip install -q -U pip
"$PY" -m pip install -q -e "$ROOT/desktop"
if [[ "$(uname -s)" == "Darwin" ]]; then
  "$PY" -m pip install -q "pyobjc-framework-Quartz>=10,<12" "pyobjc-framework-ApplicationServices>=10,<12" "pyobjc-framework-Cocoa>=10,<12" || true
fi

export ADMEASY_BACKEND="$BACKEND"
"$PY" -m admeasy_desktop register-handler
"$PY" -m admeasy_desktop install-service

if [[ -n "$PAIR" ]]; then
  set +e
  "$PY" -m admeasy_desktop pair "$PAIR"
  rc=$?
  set -e
  if [[ "$rc" -eq 2 ]]; then
    echo "Pairing codes are not on the backend yet. Open Admeasy and sign in with Google."
  elif [[ "$rc" -ne 0 ]]; then
    exit "$rc"
  fi
else
  echo "Helper installed. Open the Admeasy app from Applications (or run: $PY -m admeasy_desktop run)"
fi

echo "Backend: $BACKEND"
echo "Config folder: $HOME/.admeasy"
