"""Where the loopback UI files live (source tree vs PyInstaller bundle)."""
from __future__ import annotations

from pathlib import Path

from ..runtime import frozen, resource_root


def ui_dir() -> Path:
    if frozen():
        return resource_root() / "admeasy_desktop" / "ui"
    return Path(__file__).resolve().parent
