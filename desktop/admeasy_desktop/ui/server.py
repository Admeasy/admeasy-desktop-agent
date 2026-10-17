"""The plain window: sign in, connected devices, permissions, a few switches. Local HTTP on 127.0.0.1 only."""
from __future__ import annotations

import http.server
import json
import platform
import threading
from pathlib import Path

import httpx

from .. import auth, permissions, system_hooks
from ..api import DEVICES_DISABLED, DEVICES_NOT_DEPLOYED, DevicesDisabledError, DevicesNotDeployedError, raise_for_devices
from ..config import Settings
from ..runtime import app_executable
from ..log_buffer import tail

INDEX = Path(__file__).with_name("index.html")


class UiState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.online, self.detail, self.logging_in, self.error = False, "", False, ""
        self.agent = None

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

    def login(self) -> None:
        def run():
            self.logging_in, self.error = True, ""
            try:
                tok = auth.login_via_browser(self.settings.backend)
                for k in ("access_token", "refresh_token", "email"):
                    auth.save_secret(k, tok[k])
                from ..agent import Agent
                auth.enrol(self.settings, Agent(self.settings).capabilities(), platform.platform())
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

    def logout(self) -> None:
        tok, dev = auth.load_secret("access_token"), auth.load_secret("device_id")
        if tok and dev:
            try:
                httpx.delete(f"{self.settings.backend.rstrip('/')}/devices/{dev}", headers={"Authorization": f"Bearer {tok}"}, timeout=8)
            except Exception:
                pass
        auth.clear_secrets()

    def snapshot(self) -> dict:
        s = auth.state()
        obj = {}
        ext = {"installed": False}
        if self.agent:
            obj = {
                "objective_id": self.agent.objective_id,
                "step": self.agent.objective_step,
                "rows_so_far": self.agent.rows_so_far,
                "blocker": self.agent.blocker,
            }
            from ..browser_bridge import extension_status

            ext = extension_status()
        return {
            **s,
            "online": self.online,
            "detail": self.detail,
            "logging_in": self.logging_in,
            "error": self.error,
            "permissions": permissions.check(),
            "settings": vars(self.settings),
            "devices": self.devices() if s["signed_in"] else [],
            "objective": obj,
            "extension": ext,
        }


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

        def do_GET(self):
            if self.path == "/api/state":
                return self._json(state.snapshot())
            if self.path == "/api/logs":
                return self._json({"lines": tail(150)})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX.read_bytes())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            name = self.path.removeprefix("/api/")
            if name == "login":
                state.login()
            elif name == "logout":
                state.logout()
            elif name == "open_settings":
                permissions.open_settings(body.get("which", ""))
            elif name == "settings":
                for k, v in body.items():
                    if k in ("approval_mode", "keep_awake", "start_at_login", "paused") and hasattr(state.settings, k):
                        setattr(state.settings, k, v)
                state.settings.save()
                system_hooks.keep_awake(state.settings.keep_awake and not state.settings.paused)
                system_hooks.set_autostart(state.settings.start_at_login)
            elif name == "install_extension":
                from ..browser_bridge import full_extension_setup

                return self._json({"ok": True, **full_extension_setup()})
            return self._json({"ok": True})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
