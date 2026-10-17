"""Paths and settings. Everything lives under ~/.admeasy (like Hermes' ~/.hermes): config.json, chrome-profile/, logs/."""
from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HOME = Path(os.environ.get("ADMEASY_HOME", Path.home() / ".admeasy"))
CONFIG_PATH = HOME / "config.json"
PROFILE_DIR = HOME / "chrome-profile"
LOG_DIR = HOME / "logs"
DEFAULT_BACKEND = os.environ.get(
    "ADMEASY_BACKEND",
    "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com",
)


def platform_name() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def default_device_name() -> str:
    return platform.node().removesuffix(".local") or f"{platform_name()}-computer"


@dataclass
class Settings:
    backend: str = DEFAULT_BACKEND
    device_name: str = field(default_factory=default_device_name)
    # ask_always: every action asks. ask_risky: shell/delete/overwrite/send ask, the rest run. trusted: nothing asks
    # except the hard-blocked list. The phone answers approvals; the desktop never asks locally unless nobody replies.
    approval_mode: str = "ask_risky"
    shared_folders: list[str] = field(default_factory=lambda: [str(Path.home() / d) for d in
                                                                ("Downloads", "Desktop", "Documents")])
    keep_awake: bool = True
    start_at_login: bool = True
    paused: bool = False

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(CONFIG_PATH.read_text())
            return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()

    def save(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass


def ws_url(backend: str, path: str) -> str:
    return backend.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + path
