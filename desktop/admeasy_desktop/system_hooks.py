"""Keep the machine awake while Admeasy runs, and start the app at login."""
from __future__ import annotations

import ctypes
import os
import plistlib
import subprocess
import sys
from pathlib import Path

_caf: subprocess.Popen | None = None


def keep_awake(on: bool) -> None:
    """Prevent idle sleep (display may still sleep). A closed lid still sleeps a laptop unless it is on power with an
    external display: no software can change that."""
    global _caf
    if sys.platform == "darwin":
        if on and not _caf:
            _caf = subprocess.Popen(["caffeinate", "-i", "-s"])  # -s only holds on AC power; -i holds idle sleep
        elif not on and _caf:
            _caf.terminate()
            _caf = None
    elif sys.platform == "win32":
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def set_autostart(on: bool, exe: str | None = None) -> None:
    exe = exe or sys.executable
    if sys.platform == "darwin":
        p = Path.home() / "Library/LaunchAgents/ai.admeasy.desktop.plist"
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(plistlib.dumps({"Label": "ai.admeasy.desktop", "ProgramArguments": [exe, "run", "--background"],
                                          "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False}}))
        elif p.exists():
            p.unlink()
    elif sys.platform == "win32":
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if on:
            winreg.SetValueEx(k, "Admeasy", 0, winreg.REG_SZ, f'"{exe}" run --background')
        else:
            try:
                winreg.DeleteValue(k, "Admeasy")
            except FileNotFoundError:
                pass
