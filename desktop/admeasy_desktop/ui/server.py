"""The plain window: sign in, connected devices, permissions, a few switches. Local HTTP on 127.0.0.1 only."""
from __future__ import annotations

import http.server
import json
import logging
import platform
import secrets
import threading
import time
from pathlib import Path

import httpx

from .. import auth, permissions, system_hooks
from ..backend_client import BackendError
from ..chat_bridge import ChatBridge
from .actions import asset_bytes, handle_post, live_payload, public_state
from .backend_routes import backend_error_response, handle_backend_delete, handle_backend_get, handle_backend_post
from ..api import DEVICES_DISABLED, DEVICES_NOT_DEPLOYED, DevicesDisabledError, DevicesNotDeployedError, raise_for_devices
from ..config import Settings
from ..entitlements import EntitlementsAuthError, EntitlementsClient, EntitlementsError, InviteError
from ..runtime import app_executable
from ..log_buffer import tail
from .paths import load_index_html, ui_dir, ui_file, validate_ui_bundle

_ui_log = logging.getLogger("admeasy-desktop.ui")


class UiState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.online, self.detail, self.logging_in, self.error = False, "", False, ""
        self.agent = None
        self.token = secrets.token_urlsafe(24)
        self.chat = ChatBridge(settings)
        self.entitlements = EntitlementsClient(settings.backend)
        self._ent_cache = None
        self._ent_at = 0.0
        self._ent_error = ""

    def set_status(self, online: bool, detail: str) -> None:
        self.online, self.detail = online, detail

    def devices(self) -> list:
        tok = auth.load_secret("access_token")
        if not tok:
            return []
        try:
            r = httpx.get(f"{self.settings.backend.rstrip('/')}/devices", headers={"Authorization": f"Bearer {tok}"}, timeout=8)
            if r.status_code == 401 and auth.refresh(self.settings.backend):
                return self.devices()
            raise_for_devices(r)
            return r.json().get("devices", []) if r.status_code == 200 else []
        except DevicesDisabledError:
            self.error = DEVICES_DISABLED
            return []
        except DevicesNotDeployedError:
            self.error = DEVICES_NOT_DEPLOYED
            return []
        except Exception:
            return []

    def submit_invite(self, code: str) -> None:
        self.error = ""
        try:
            got = self.entitlements.validate_invite(code)
        except InviteError as exc:
            auth.save_secret("pending_invite", "")
            self.error = str(exc)
            return
        except EntitlementsError as exc:
            self.error = str(exc)
            return
        auth.save_secret("pending_invite", got.normalized_code)

    def login(self, existing: bool = False) -> None:
        def run():
            self.logging_in, self.error = True, ""
            try:
                invite = None if existing else (auth.load_secret("pending_invite") or "")
                if existing:
                    auth.save_secret("pending_invite", "")
                    invite = None
                elif not invite:
                    self.error = "Enter an invite code first."
                    return
                tok = auth.login_via_browser(self.settings.backend, invite=invite)
                auth.save_secrets({k: tok[k] for k in ("access_token", "refresh_token", "email")})
                self._ent_cache = None
                snap = self._load_entitlements(fresh=True)
                if snap is None or not snap.invited:
                    self.error = self._ent_error or (
                        "This account isn't invited yet. Enter a code, then sign in with Google again "
                        "so the invite is saved on the account."
                    )
                    return
                auth.save_secret("pending_invite", "")
                from ..agent import Agent
                agent = self.agent or Agent(self.settings)
                agent._snap = snap
                auth.enrol(self.settings, agent.capabilities(), platform.platform())
                permissions.check(prompt=True)  # first-run: triggers the macOS Screen Recording / Accessibility prompts
                self.settings.start_at_login = True
                self.settings.save()
                system_hooks.set_autostart(True, app_executable())
            except (DevicesDisabledError, DevicesNotDeployedError) as e:
                self.error = str(e)
            except Exception as e:
                self.error = f"Sign-in failed: {e}"
            finally:
                self.logging_in = False
        threading.Thread(target=run, daemon=True).start()

    def _load_entitlements(self, fresh: bool = False):
        if not auth.load_secret("refresh_token") and not auth.load_secret("access_token"):
            return None
        now = time.monotonic()
        if not fresh and self._ent_cache is not None and (now - self._ent_at) < 15:
            return self._ent_cache
        try:
            snap = self.entitlements.me(fresh=fresh)
        except EntitlementsAuthError:
            self._ent_error = "Sign in again to check your plan."
            return self._ent_cache
        except EntitlementsError as exc:
            self._ent_error = str(exc)
            return self._ent_cache
        self._ent_cache = snap
        self._ent_at = now
        self._ent_error = ""
        if self.agent is not None:
            self.agent._snap = snap
        return snap

    def logout(self) -> None:
        tok, dev = auth.load_secret("access_token"), auth.load_secret("device_id")
        if tok and dev:
            try:
                httpx.delete(f"{self.settings.backend.rstrip('/')}/devices/{dev}", headers={"Authorization": f"Bearer {tok}"}, timeout=8)
            except Exception:
                pass
        auth.clear_secrets()
        self._ent_cache = None
        self._ent_error = ""

    def snapshot(self) -> dict:
        s = auth.state()
        obj = {}
        if self.agent:
            obj = {
                "objective_id": self.agent.objective_id,
                "step": self.agent.objective_step,
                "rows_so_far": self.agent.rows_so_far,
                "blocker": self.agent.blocker,
            }
            agent_ui = self.agent.session.public()
        else:
            agent_ui = {"agent_active": False, "agent_pulse": False}
        snap = self._load_entitlements() if s["signed_in"] else None
        invited = bool(snap and snap.invited)
        pending = auth.load_secret("pending_invite") or ""
        data = {
            **s,
            "online": self.online,
            "detail": self.detail,
            "logging_in": self.logging_in,
            "error": self.error or (self._ent_error if s["signed_in"] and snap is None else ""),
            "permissions": permissions.check(),
            "settings": vars(self.settings),
            "devices": self.devices() if s["signed_in"] and invited else [],
            "objective": obj,
            "invited": invited,
            "needs_invite": not (s["signed_in"] and invited),
            "pending_invite": pending,
            "entitlements": snap.public() if snap else None,
            "agent_active": agent_ui.get("agent_active", False),
            "agent_pulse": agent_ui.get("agent_pulse", False),
        }
        return public_state(self, data)


def serve(state: UiState, port: int = 0) -> tuple[http.server.HTTPServer, int]:
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

        def _csrf(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = self.headers.get("Host") or ""
            if origin not in (f"http://{host}", f"https://{host}"):
                return False
            got = self.headers.get("X-Admeasy-Token") or ""
            return secrets.compare_digest(got, state.token)

        def _bytes(self, data: bytes, content_type: str):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                self._do_get()
            except Exception:
                _ui_log.exception("GET %s failed", self.path)
                try:
                    self._json({"error": "internal error"}, 500)
                except Exception:
                    pass

        def _do_get(self):
            path = self.path.split("?", 1)[0]
            if path in ("", "/"):
                path = "/"
            if path == "/api/state":
                return self._json(state.snapshot())
            if path == "/api/logs":
                return self._json({"lines": tail(150)})
            if path == "/api/chat/history":
                return self._json(state.chat.history())
            if path == "/api/live":
                return self._json(live_payload(state))
            if path.startswith("/api/backend/"):
                name = path.removeprefix("/api/backend/").strip("/")
                try:
                    payload = handle_backend_get(state, name)
                except BackendError as exc:
                    body, code = backend_error_response(exc)
                    return self._json(body, code)
                if payload is None:
                    return self._json({"error": "unknown route"}, 404)
                return self._json(payload)
            if path in ("/install.sh", "/install.ps1"):
                blob = asset_bytes(path.lstrip("/"))
                if blob is None:
                    return self._json({"error": "installer missing"}, 404)
                return self._bytes(blob, "text/plain; charset=utf-8")
            static = {
                "/theme.css": ("theme.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                "/sw.js": ("sw.js", "application/javascript; charset=utf-8"),
                "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
            }
            if path in static:
                name, ctype = static[path]
                asset = ui_file(name)
                return self._bytes(asset.read_bytes(), ctype)
            if path.startswith("/icons/hand/") and path.endswith(".png"):
                rel = path.removeprefix("/")
                asset = ui_dir() / rel
                if asset.is_file():
                    return self._bytes(asset.read_bytes(), "image/png")
                return self._json({"error": "icon not found"}, 404)
            if path in ("/", "/index.html"):
                html = load_index_html(state.token)
                return self._bytes(html.encode("utf-8"), "text/html; charset=utf-8")
            return self._json({"error": "not found"}, 404)

        def _backend_write(self, route: str, body: dict | None = None):
            try:
                payload = handle_backend_post(state, route, body or {})
            except BackendError as exc:
                b, code = backend_error_response(exc)
                return self._json(b, code)
            if payload is None:
                return self._json({"error": "unknown route"}, 404)
            return self._json(payload)

        def do_DELETE(self):
            if not self._csrf():
                return self._json({"error": "blocked"}, 403)
            name = self.path.removeprefix("/api/")
            if not name.startswith("backend/"):
                return self._json({"error": "not found"}, 404)
            route = name.removeprefix("backend/").strip("/")
            try:
                payload = handle_backend_delete(state, route)
            except BackendError as exc:
                b, code = backend_error_response(exc)
                return self._json(b, code)
            if payload is None:
                return self._json({"error": "unknown route"}, 404)
            return self._json(payload)

        def do_POST(self):
            if not self._csrf():
                return self._json({"error": "blocked"}, 403)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            name = self.path.removeprefix("/api/")
            if name.startswith("backend/"):
                route = name.removeprefix("backend/").strip("/")
                return self._backend_write(route, body)
            try:
                extra = handle_post(state, name, body)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            if extra is not None:
                return self._json(extra)
            if name == "invite":
                state.submit_invite(str(body.get("code") or ""))
            elif name == "login":
                state.login(existing=bool(body.get("existing")))
            elif name == "logout":
                state.logout()
            elif name == "open_settings":
                permissions.open_settings(body.get("which", ""))
            elif name == "settings":
                for k, v in body.items():
                    if k in (
                        "approval_mode",
                        "keep_awake",
                        "start_at_login",
                        "paused",
                        "show_agent_cursor",
                        "show_agent_edge_border",
                    ) and hasattr(
                        state.settings, k
                    ):
                        setattr(state.settings, k, v)
                        if k == "approval_mode":
                            state.settings.approval_mode_chosen = True
                state.settings.save()
                system_hooks.keep_awake(state.settings.keep_awake and not state.settings.paused)
                system_hooks.set_autostart(state.settings.start_at_login)
            return self._json({"ok": True})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)

    def _serve_forever() -> None:
        try:
            srv.serve_forever()
        except Exception:
            _ui_log.exception("UI HTTP server stopped")

    threading.Thread(target=_serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
