"""Frozen-app detection (PyInstaller bundle)."""
from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_executable() -> str:
    return sys.executable


def bundle_root() -> Path:
    """Directory that contains admeasy_desktop/ui in a packaged build."""
    if frozen():
        if hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS)
            if (meipass / "admeasy_desktop" / "ui" / "index.html").is_file():
                return meipass
        exe = Path(sys.executable).resolve()
        candidates: list[Path] = []
        if sys.platform == "darwin":
            # Admeasy.app/Contents/MacOS/Admeasy
            candidates.extend([
                exe.parent / "_internal",
                exe.parent.parent / "Frameworks",
                exe.parent.parent / "Resources",
            ])
        else:
            candidates.extend([exe.parent / "_internal", exe.parent])
        for root in candidates:
            if (root / "admeasy_desktop" / "ui" / "index.html").is_file():
                return root
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    return bundle_root()
