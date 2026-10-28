"""Google sign-in for the desktop app and device enrolment.

Tokens live in ~/.admeasy/secrets.json for the bundled .app (no repeated Keychain
password prompts). Developers can force Keychain with ADMEASY_SECRETS=keychain.
"""
from __future__ import annotations

import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser

import httpx

from . import VERSION
from .api import DevicesDisabledError, raise_for_devices
from .config import Settings, platform_name
from . import config as config_mod
from .runtime import frozen

SERVICE = "ai.admeasy.desktop"
_STORE = "secrets.json"


def _use_keychain() -> bool:
    mode = os.environ.get("ADMEASY_SECRETS", "auto").lower()
    if mode in ("file", "0", "false", "no"):
        return False
    if mode in ("keychain", "1", "true", "yes"):
        return True
    # Bundled app: one file, one folder users understand; avoids 5–10 login prompts.
    if frozen():
        return False
    try:
        import keyring  # noqa: F401
    except Exception:
        return False
    return True


def _kr():
    if not _use_keychain():
        return None
    try:
        import keyring
        return keyring
    except Exception:
        return None


def _file_path():
    return config_mod.HOME / _STORE


def _read_file() -> dict:
    p = _file_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_file(data: dict) -> None:
    config_mod.HOME.mkdir(parents=True, exist_ok=True)
    p = _file_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _load_blob() -> dict:
    kr = _kr()
    if kr:
        try:
            raw = kr.get_password(SERVICE, _STORE)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return _read_file()


def _save_blob(data: dict) -> None:
    kr = _kr()
    if kr:
        try:
            kr.set_password(SERVICE, _STORE, json.dumps(data))
            return
        except Exception:
            pass
    _write_file(data)


def save_secret(name: str, value: str) -> None:
    data = _load_blob()
    data[name] = value
    _save_blob(data)


def save_secrets(values: dict[str, str]) -> None:
    data = _load_blob()
    data.update({k: v for k, v in values.items() if v is not None})
    _save_blob(data)


def load_secret(name: str) -> str | None:
    v = _load_blob().get(name)
    return str(v) if v is not None and v != "" else None


def clear_device_secrets() -> None:
    data = _load_blob()
    for n in ("device_id", "device_token"):
        data.pop(n, None)
    _save_blob(data)


def clear_secrets() -> None:
    kr = _kr()
    if kr:
        try:
            kr.delete_password(SERVICE, _STORE)
        except Exception:
            pass
    p = _file_path()
    if p.exists():
        p.unlink()


def _free_port() -> int:
    for _ in range(40):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if 1024 <= port <= 65535:
            return port
    raise RuntimeError("could not bind a loopback port in 1024–65535")


def _sign_in_nonce() -> str:
    return secrets.token_urlsafe(32)[:64]


def login_via_browser(backend: str, timeout_s: int = 300, open_browser=webbrowser.open, invite: str | None = None) -> dict:
    port, nonce = _free_port(), _sign_in_nonce()
    got: dict = {}
    done = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path != "/callback" or not secrets.compare_digest(q.get("nonce", ""), nonce):
                self.send_response(400)
                self.end_headers()
                return
            got.update({k: q.get(k, "") for k in ("access_token", "refresh_token", "email")})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h3>Signed in. You can close this tab and return to Admeasy.</h3>")
            done.set()

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        query = {"desktop_port": port, "nonce": nonce}
        if invite and str(invite).strip():
            query["invite"] = str(invite).strip()
        open_browser(f"{backend.rstrip('/')}/auth/google/start?" + urllib.parse.urlencode(query))
        if not done.wait(timeout_s) or not got.get("access_token"):
            raise TimeoutError("sign-in did not finish")
    finally:
        srv.shutdown()
    return got


def refresh(backend: str) -> str | None:
    rt = load_secret("refresh_token")
    if not rt:
        return None
    try:
        r = httpx.post(f"{backend.rstrip('/')}/auth/refresh", json={"refresh_token": rt}, timeout=20)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    j = r.json()
    updates = {"access_token": j["access_token"]}
    if j.get("refresh_token"):
        updates["refresh_token"] = j["refresh_token"]
    save_secrets(updates)
    return j["access_token"]


def enrol(settings: Settings, capabilities: dict, os_version: str) -> dict:
    existing = load_secret("device_id"), load_secret("device_token")
    if existing[0] and existing[1]:
        return {"device_id": existing[0], "device_token": existing[1]}
    tok = refresh(settings.backend) or load_secret("access_token")
    body = {"name": settings.device_name, "platform": platform_name(), "os_version": os_version,
            "capabilities": capabilities}
    for attempt in range(2):
        r = httpx.post(f"{settings.backend.rstrip('/')}/devices/register", json=body,
                       headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        if r.status_code == 401 and attempt == 0:
            tok = refresh(settings.backend)
            if tok:
                continue
        raise_for_devices(r)
        r.raise_for_status()
        j = r.json()
        save_secrets({"device_id": j["device_id"], "device_token": j["device_token"]})
        return j
    raise RuntimeError("could not register this computer")


def state() -> dict:
    return {"signed_in": bool(load_secret("refresh_token")), "email": load_secret("email"),
            "device_id": load_secret("device_id"), "version": VERSION, "ts": int(time.time())}
