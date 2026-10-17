"""Google sign-in for the desktop app and device enrolment.

Flow (same Google OAuth app and redirect URI as the phone, so no new Google Cloud setup):
  1. open the system browser at  {backend}/auth/google/start?desktop_port=<p>&nonce=<n>
  2. the backend finishes Google OAuth and redirects to http://127.0.0.1:<p>/callback?access_token=...&nonce=<n>
  3. this module's loopback server checks the nonce, stores the tokens in the OS keychain
  4. POST /devices/register with the user's JWT -> device_id + device_token (shown once, stored in the keychain)
The same Google account yields the same Admeasy user id on phone and computer, so the phone can see this device.
"""
from __future__ import annotations

import http.server
import json
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser

import httpx

from . import VERSION
from .api import DevicesDisabledError, raise_for_devices
from .config import HOME, Settings, platform_name

SERVICE = "ai.admeasy.desktop"


def _kr():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def save_secret(name: str, value: str) -> None:
    kr = _kr()
    try:
        if kr:
            kr.set_password(SERVICE, name, value)
            return
    except Exception:
        pass
    HOME.mkdir(parents=True, exist_ok=True)  # keychain unavailable (headless Linux): 0600 file fallback
    p = HOME / "secrets.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    d[name] = value
    p.write_text(json.dumps(d))
    p.chmod(0o600)


def load_secret(name: str) -> str | None:
    kr = _kr()
    try:
        if kr:
            v = kr.get_password(SERVICE, name)
            if v:
                return v
    except Exception:
        pass
    p = HOME / "secrets.json"
    return json.loads(p.read_text()).get(name) if p.exists() else None


def clear_device_secrets() -> None:
    for n in ("device_id", "device_token"):
        kr = _kr()
        try:
            if kr:
                kr.delete_password(SERVICE, n)
        except Exception:
            pass
    p = HOME / "secrets.json"
    if p.exists():
        d = json.loads(p.read_text())
        for n in ("device_id", "device_token"):
            d.pop(n, None)
        p.write_text(json.dumps(d))
        p.chmod(0o600)


def clear_secrets() -> None:
    for n in ("access_token", "refresh_token", "email", "device_id", "device_token"):
        kr = _kr()
        try:
            if kr:
                kr.delete_password(SERVICE, n)
        except Exception:
            pass
    p = HOME / "secrets.json"
    if p.exists():
        p.unlink()


def _free_port() -> int:
    """Loopback port in 1024–65535 (backend ignores desktop_port outside this range)."""
    for _ in range(40):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if 1024 <= port <= 65535:
            return port
    raise RuntimeError("could not bind a loopback port in 1024–65535")


def _sign_in_nonce() -> str:
    return secrets.token_urlsafe(32)[:64]


def login_via_browser(backend: str, timeout_s: int = 300, open_browser=webbrowser.open) -> dict:
    """Blocks until the browser hands the tokens back. Returns {access_token, refresh_token, email}."""
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
        open_browser(f"{backend.rstrip('/')}/auth/google/start?" + urllib.parse.urlencode(
            {"desktop_port": port, "nonce": nonce}))
        if not done.wait(timeout_s) or not got.get("access_token"):
            raise TimeoutError("sign-in did not finish")
    finally:
        srv.shutdown()
    return got


def refresh(backend: str) -> str | None:
    rt = load_secret("refresh_token")
    if not rt:
        return None
    r = httpx.post(f"{backend.rstrip('/')}/auth/refresh", json={"refresh_token": rt}, timeout=20)
    if r.status_code != 200:
        return None
    j = r.json()
    save_secret("access_token", j["access_token"])
    if j.get("refresh_token"):
        save_secret("refresh_token", j["refresh_token"])
    return j["access_token"]


def enrol(settings: Settings, capabilities: dict, os_version: str) -> dict:
    """Register this computer under the signed-in account (once)."""
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
        save_secret("device_id", j["device_id"])
        save_secret("device_token", j["device_token"])
        return j
    raise RuntimeError("could not register this computer")


def state() -> dict:
    return {"signed_in": bool(load_secret("refresh_token")), "email": load_secret("email"),
            "device_id": load_secret("device_id"), "version": VERSION, "ts": int(time.time())}
