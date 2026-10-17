"""Chromium extension + native messaging bridge (structured browser ops)."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

BRIDGE_ROOT = Path.home() / ".admeasy" / "bridge"
INBOX = BRIDGE_ROOT / "inbox"
OUTBOX = BRIDGE_ROOT / "outbox"
INSTALL_MARKER = BRIDGE_ROOT / "installed.json"
HOST_NAME = "com.admeasy.desktop"


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
    }


def register_install(browsers: list[str] | None = None) -> None:
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
                "updated_at": int(time.time()),
            }
        )
    )


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
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/NativeMessagingHosts"
    return None


def install_native_host(host_script: Path) -> list[str]:
    """Write native messaging manifest pointing at host_script. Returns browsers configured."""
    done: list[str] = []
    manifest = {
        "name": HOST_NAME,
        "description": "Admeasy desktop browser bridge",
        "path": str(host_script.resolve()),
        "type": "stdio",
        "allowed_origins": ["chrome-extension://admeasy-bridge-placeholder/"],
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
        register_install(done)
    return done


def request(op: str, params: dict, timeout_s: float = 45.0) -> dict | None:
    """Send op to extension via inbox/outbox files (native host mirrors this)."""
    if not extension_status().get("installed"):
        return None
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
