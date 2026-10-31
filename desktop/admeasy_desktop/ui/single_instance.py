"""Detect a running loopback UI and hand off instead of starting a second server."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import HOME

log = logging.getLogger("admeasy-desktop")
REGISTRY = HOME / "ui-server.json"
_LOCK_PATH = HOME / "ui-server.lock"
_MUTEX = None
_LOCK_FD: int | None = None


def _mutex_name() -> str:
    return "Global\\AdmeasyDesktopAgent" if sys.platform == "win32" else "AdmeasyDesktopAgent"


def try_acquire_primary() -> bool:
    """Return True if this process should start the UI server."""
    global _MUTEX, _LOCK_FD
    HOME.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183
            handle = kernel32.CreateMutexW(None, False, _mutex_name())
            if not handle:
                return True
            _MUTEX = handle
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                return False
            return True
        except Exception as exc:
            log.warning("single-instance mutex unavailable (%s); continuing", exc)
            return True
    try:
        import fcntl

        fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FD = fd
        return True
    except BlockingIOError:
        return False
    except Exception as exc:
        log.warning("single-instance flock unavailable (%s); continuing", exc)
        return True


def write_registry(port: int, token: str) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(
        json.dumps({"port": port, "token": token, "pid": os.getpid(), "ts": int(time.time())}),
        encoding="utf-8",
    )


def clear_registry() -> None:
    try:
        REGISTRY.unlink(missing_ok=True)
    except OSError:
        pass


def read_registry() -> dict | None:
    if not REGISTRY.is_file():
        return None
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def probe_ui(port: int, timeout: float = 1.5) -> bool:
    url = f"http://127.0.0.1:{port}/api/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return res.status == 200
    except Exception:
        return False


def focus_existing() -> bool:
    """Best-effort: bring an already-running window forward."""
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "Admeasy")
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                return True
        except Exception:
            pass
    return False


def handoff_to_running_instance() -> bool:
    """If another UI server is healthy, focus it and return True (caller should exit)."""
    reg = read_registry()
    if not reg:
        return False
    port = int(reg.get("port") or 0)
    if port <= 0:
        return False
    if not probe_ui(port):
        clear_registry()
        return False
    focus_existing()
    url = f"http://127.0.0.1:{port}/"
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass
    log.info("handed off to existing Admeasy UI on %s", url)
    print(f"Admeasy is already running at {url}", flush=True)
    return True
