"""Chromium extension + native messaging bridge (structured browser ops)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .bridge_server import client_count, request_socket, start as start_bridge_server
from .extension_identity import ALLOWED_ORIGIN, EXTENSION_ID, MANIFEST_KEY_B64

BRIDGE_ROOT = Path.home() / ".admeasy" / "bridge"
EXT_INSTALL_DIR = Path.home() / ".admeasy" / "extension"
HOST_INSTALL_DIR = Path.home() / ".admeasy" / "native_host"
INBOX = BRIDGE_ROOT / "inbox"
OUTBOX = BRIDGE_ROOT / "outbox"
INSTALL_MARKER = BRIDGE_ROOT / "installed.json"
HOST_NAME = "com.admeasy.desktop"


def _bundle_root() -> Path:
    from .runtime import resource_root

    r = resource_root()
    return r if (r / "browser_extension").is_dir() else Path(__file__).resolve().parents[1]


def extension_source_dir() -> Path:
    root = _bundle_root()
    cand = root / "browser_extension"
    if cand.is_dir():
        return cand
    return Path(__file__).resolve().parents[1] / "browser_extension"


def host_source_script() -> Path:
    root = _bundle_root()
    cand = root / "native_host" / "admeasy_host.py"
    if cand.is_file():
        return cand
    return Path(__file__).resolve().parents[1] / "native_host" / "admeasy_host.py"


def extension_status() -> dict:
    meta = {}
    if INSTALL_MARKER.is_file():
        try:
            meta = json.loads(INSTALL_MARKER.read_text())
        except Exception:
            meta = {}
    return {
        "installed": bool(meta.get("installed")),
        "version": meta.get("version"),
        "host_registered": bool(meta.get("host_registered")),
        "browsers": meta.get("browsers") or [],
        "extension_id": EXTENSION_ID,
        "extension_loaded": (EXT_INSTALL_DIR / "manifest.json").is_file(),
        "native_clients": client_count(),
    }


def register_install(browsers: list[str] | None = None, **extra) -> None:
    BRIDGE_ROOT.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(exist_ok=True)
    OUTBOX.mkdir(exist_ok=True)
    INSTALL_MARKER.write_text(
        json.dumps(
            {
                "installed": True,
                "version": "0.4.0",
                "host_registered": True,
                "browsers": browsers or ["chrome"],
                "extension_id": EXTENSION_ID,
                "updated_at": int(time.time()),
                **extra,
            }
        )
    )


def _copy_extension_tree() -> Path:
    src = extension_source_dir()
    if not src.is_dir():
        raise FileNotFoundError(f"extension sources missing at {src}")
    if EXT_INSTALL_DIR.exists():
        shutil.rmtree(EXT_INSTALL_DIR)
    shutil.copytree(src, EXT_INSTALL_DIR)
    manifest = json.loads((EXT_INSTALL_DIR / "manifest.json").read_text())
    manifest["key"] = MANIFEST_KEY_B64
    (EXT_INSTALL_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return EXT_INSTALL_DIR


def _install_host_launcher() -> Path:
    from .runtime import app_executable, frozen

    HOST_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    exe = app_executable()
    if frozen():
        if sys.platform == "win32":
            cmd = HOST_INSTALL_DIR / "admeasy_host.cmd"
            cmd.write_text(f'@echo off\r\n"{exe}" bridge-host\r\n')
            return cmd
        sh = HOST_INSTALL_DIR / "run_host.sh"
        sh.write_text(f'#!/usr/bin/env bash\nexec "{exe}" bridge-host\n')
        sh.chmod(0o755)
        return sh
    host_py = HOST_INSTALL_DIR / "admeasy_host.py"
    shutil.copy2(host_source_script(), host_py)
    if sys.platform == "win32":
        cmd = HOST_INSTALL_DIR / "admeasy_host.cmd"
        cmd.write_text(f'@echo off\r\n"{exe}" bridge-host\r\n')
        return cmd
    sh = HOST_INSTALL_DIR / "run_host.sh"
    sh.write_text(f'#!/usr/bin/env bash\nexec "{exe}" bridge-host\n')
    sh.chmod(0o755)
    return sh


def native_host_manifest_path(browser: str) -> Path | None:
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
        mapping = {
            "chrome": base / "Google/Chrome/NativeMessagingHosts",
            "edge": base / "Microsoft Edge/NativeMessagingHosts",
            "brave": base / "BraveSoftware/Brave-Browser/NativeMessagingHosts",
        }
        return mapping.get(browser)
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "")
        mapping = {
            "chrome": Path(la) / "Google/Chrome/NativeMessagingHosts",
            "edge": Path(la) / "Microsoft/Edge/NativeMessagingHosts",
            "brave": Path(la) / "BraveSoftware/Brave-Browser/NativeMessagingHosts",
        }
        return mapping.get(browser)
    return Path.home() / ".config" / "google-chrome/NativeMessagingHosts"


def install_native_host(host_script: Path | None = None) -> list[str]:
    """Copy extension + host, register native messaging manifests with real extension id."""
    start_bridge_server()
    ext_dir = _copy_extension_tree()
    launcher = host_script or _install_host_launcher()
    done: list[str] = []
    manifest = {
        "name": HOST_NAME,
        "description": "Admeasy desktop browser bridge",
        "path": str(launcher.resolve()),
        "type": "stdio",
        "allowed_origins": [ALLOWED_ORIGIN],
    }
    for browser in ("chrome", "edge", "brave"):
        dest_dir = native_host_manifest_path(browser)
        if dest_dir is None:
            continue
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / f"{HOST_NAME}.json").write_text(json.dumps(manifest, indent=2))
            done.append(browser)
        except OSError:
            continue
    if done:
        register_install(done, extension_path=str(ext_dir))
    return done


def open_extension_load_ui() -> None:
    """Open browser extensions page; user loads unpacked from ~/.admeasy/extension."""
    ext_dir = str(EXT_INSTALL_DIR)
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Google Chrome", "chrome://extensions"])
    elif sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "chrome", "chrome://extensions"])
    else:
        subprocess.Popen(["xdg-open", "chrome://extensions"])
    (BRIDGE_ROOT / "LOAD_UNPACKED.txt").write_text(
        f"Load unpacked extension from:\n{ext_dir}\n\nExtension ID (fixed): {EXTENSION_ID}\n"
    )


def full_extension_setup() -> dict:
    browsers = install_native_host()
    open_extension_load_ui()
    return {"browsers": browsers, "extension_id": EXTENSION_ID, "extension_path": str(EXT_INSTALL_DIR)}


def _request_files(op: str, params: dict, timeout_s: float) -> dict:
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    rid = str(uuid.uuid4())
    req_path = INBOX / f"{rid}.json"
    res_path = OUTBOX / f"{rid}.json"
    req_path.write_text(json.dumps({"id": rid, "op": op, "params": params}))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if res_path.is_file():
            try:
                data = json.loads(res_path.read_text())
                res_path.unlink(missing_ok=True)
                req_path.unlink(missing_ok=True)
                return data
            except Exception:
                return {"status": "error", "reason": "bridge_response_invalid"}
        time.sleep(0.05)
    req_path.unlink(missing_ok=True)
    return {"status": "timeout", "reason": "extension_bridge_timeout"}


def request(op: str, params: dict, timeout_s: float = 45.0) -> dict | None:
    if not extension_status().get("installed"):
        return None
    start_bridge_server()
    hit = request_socket(op, params, timeout_s)
    if hit is not None:
        return hit
    return _request_files(op, params, timeout_s)


async def run_browser_op(p: dict) -> dict | None:
    op = p.get("op") or ""
    mapping = {
        "list_tabs": "list_tabs",
        "open_tab": "open_tab",
        "navigate": "navigate",
        "read_page": "read_page",
        "extract": "extract",
        "query_elements": "query_elements",
        "click_element": "click_element",
        "type_element": "type_element",
        "scroll": "scroll",
        "wait_for": "wait_for",
        "screenshot_tab": "screenshot_tab",
        "close_tab": "close_tab",
    }
    bridge_op = mapping.get(op)
    if not bridge_op:
        return None
    import asyncio

    return await asyncio.get_event_loop().run_in_executor(None, request, bridge_op, p, float(p.get("timeout_s") or 45))
