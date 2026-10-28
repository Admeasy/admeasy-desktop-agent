"""Keep the machine awake while Admeasy runs, and start the app at login."""
from __future__ import annotations

import ctypes
import os
import plistlib
import shlex
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


def handler_argv(exe: str | None = None) -> list[str]:
    """Argv prefix for `handle-url`. Drops the service's `run --background`."""
    argv = [part for part in service_argv(exe) if part not in ("run", "--background")]
    return argv


def service_argv(exe: str | None = None) -> list[str]:
    """How the background service should be started.

    A frozen .app/.exe accepts `run`. A Python interpreter must use `-m admeasy_desktop`,
    otherwise macOS/Windows would launch the interpreter with a meaningless `run` argument.
    """
    from .runtime import frozen
    exe = exe or sys.executable
    name = os.path.basename(exe).lower()
    if frozen() or not name.startswith("python"):
        return [exe, "run", "--background"]
    return [exe, "-m", "admeasy_desktop", "run", "--background"]


def set_autostart(on: bool, exe: str | None = None) -> None:
    argv = service_argv(exe)
    if sys.platform == "darwin":
        p = Path.home() / "Library/LaunchAgents/ai.admeasy.desktop.plist"
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(plistlib.dumps({
                "Label": "ai.admeasy.desktop",
                "ProgramArguments": argv,
                "RunAtLoad": True,
                "KeepAlive": {"SuccessfulExit": False},
            }))
        elif p.exists():
            p.unlink()
    elif sys.platform == "linux":
        unit_dir = Path.home() / ".config/systemd/user"
        unit = unit_dir / "admeasy-desktop.service"
        if on:
            unit_dir.mkdir(parents=True, exist_ok=True)
            command = " ".join(shlex.quote(part) for part in argv)
            unit.write_text(
                "[Unit]\nDescription=Admeasy desktop helper\n\n"
                "[Service]\n"
                f"ExecStart={command}\n"
                "Restart=on-failure\n\n"
                "[Install]\nWantedBy=default.target\n",
                encoding="utf-8",
            )
            if shutil_which("systemctl"):
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                subprocess.run(["systemctl", "--user", "enable", "--now", "admeasy-desktop.service"], check=False)
        elif unit.exists():
            if shutil_which("systemctl"):
                subprocess.run(["systemctl", "--user", "disable", "--now", "admeasy-desktop.service"], check=False)
            unit.unlink()
    elif sys.platform == "win32":
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if on:
            rendered = " ".join(f'"{part}"' if " " in part else part for part in argv)
            winreg.SetValueEx(k, "Admeasy", 0, winreg.REG_SZ, rendered)
        else:
            try:
                winreg.DeleteValue(k, "Admeasy")
            except FileNotFoundError:
                pass


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
