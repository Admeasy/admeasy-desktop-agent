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
    # autopilot (default): open/click/type/navigate never ask; destructive shell/file steps, installs and final
    # sends/calls do.
    approval_mode: str = "autopilot"
    approval_mode_chosen: bool = False  # set when the user picks a mode in the UI
    # Legacy implicit roots (Downloads, Desktop, Documents). New installs set
    # use_approved_folders_only and ignore this list until the user approves each folder.
    shared_folders: list[str] = field(default_factory=lambda: [str(Path.home() / d) for d in
                                                                ("Downloads", "Desktop", "Documents")])
    approved_folders: list[str] = field(default_factory=list)
    use_approved_folders_only: bool = False
    # New configs (no file yet) turn the gate on inside load(). Existing files stay False
    # so a computer the phone already drives is not locked out.
    gate_until_onboarding: bool = False
    onboarding_complete: bool = False
    clipboard_skipped: bool = False
    capability_toggles: dict = field(default_factory=lambda: {
        "shell": True,
        "files": True,
        "screen": True,
        "input": True,
        "browser": True,
        "notify": True,
    })
    command_allowlist: list[str] = field(default_factory=list)
    command_blocklist: list[str] = field(default_factory=list)
    keep_awake: bool = True
    start_at_login: bool = True
    paused: bool = False
    # default_first: URLs in your default browser + screen/CUA for interaction (keeps your logins).
    # playwright_profile: isolated ~/.admeasy/chrome-profile (automation only).
    browser_automation: str = "default_first"
    show_agent_cursor: bool = True
    show_agent_edge_border: bool = True
    # Playwright with the real default-browser profile (e.g. Comet) so DOM automation keeps your logins.
    # Empty = auto from chromium_browsers.json; set both to override. Falls back to the isolated profile if the
    # browser is already running (Chromium locks its profile) or the paths are missing.
    playwright_real_profile: bool = True
    playwright_executable: str = ""
    playwright_user_data_dir: str = ""

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_PATH.exists():
            fresh = cls()
            # First run of this product: no implicit folders, and the computer stays idle
            # until the window's permission steps are finished.
            fresh.gate_until_onboarding = True
            fresh.use_approved_folders_only = True
            fresh.shared_folders = []
            return fresh
        try:
            raw = json.loads(CONFIG_PATH.read_text())
            if raw.get("browser_automation") == "playwright_profile" and not os.environ.get("ADMEASY_PLAYWRIGHT"):
                raw["browser_automation"] = "default_first"
            s = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
            if s.approval_mode == "ask_risky" and not s.approval_mode_chosen:
                s.approval_mode = "autopilot"  # old installs saved the previous default, not a choice
            return s
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
