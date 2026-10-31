"""Where the loopback UI files live (source tree vs PyInstaller bundle)."""
from __future__ import annotations

from pathlib import Path

from ..runtime import bundle_root, frozen


def ui_dir() -> Path:
    if frozen():
        root = bundle_root()
        bundled = root / "admeasy_desktop" / "ui"
        if bundled.is_dir():
            return bundled
    return Path(__file__).resolve().parent


def ui_file(name: str) -> Path:
    path = ui_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"UI asset missing: {path}")
    return path


def load_index_html(token: str) -> str:
    return ui_file("index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)


def validate_ui_bundle() -> list[str]:
    """Return list of missing required files (empty = ok)."""
    required = ("index.html", "app.js", "theme.css", "sw.js", "manifest.webmanifest")
    missing = []
    root = ui_dir()
    for name in required:
        if not (root / name).is_file():
            missing.append(str(root / name))
    icon = root / "icons" / "hand" / "01-computer.png"
    if not icon.is_file():
        missing.append(str(icon))
    return missing
