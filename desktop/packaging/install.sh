#!/usr/bin/env bash
# Install the Admeasy helper for the current user. No admin rights and no code-signing certificate.
# curl does not set the macOS quarantine flag, so Gatekeeper does not prompt.
# The script still asks you to read it before you pipe it to a shell.
#
#   curl -fsSL https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.sh | bash -s -- --backend https://...
#   curl -fsSL .../install.sh | bash -s -- --pair CODE --backend https://...
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
      echo "usage: install.sh [--pair CODE] [--backend URL] [--source DIR]"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python 3.11+ is required" >&2
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

PY="$HOME/.admeasy/venv/bin/python"
python3 -m venv "$HOME/.admeasy/venv"
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
  echo "Helper installed. Open Admeasy and sign in with the same Google account as your phone."
fi

echo "Backend: $BACKEND"
echo "The background service is registered. On macOS it is a LaunchAgent; on Linux a systemd user service."
