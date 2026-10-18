#!/usr/bin/env python3
"""Run contract conformance tests (same fixture as backend)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rc = subprocess.call(
    [sys.executable, "-m", "pytest", "-q", "desktop/tests/test_cua_conformance.py"],
    cwd=ROOT,
)
sys.exit(rc)
