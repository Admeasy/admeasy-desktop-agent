"""Desktop chat against the same Lightsail backend as WhatsApp and the phone.

History: GET /conversations and GET /conversations/{id}/messages with the user JWT.
Send: WebSocket /ws/session?token=&conversation_id=  (defined in this repo's backend
copy). The live image probed on 28 Oct 2026 returned 404 for that path; the window
shows that error and still loads history when the REST calls succeed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import urllib.parse

import httpx
import websockets

from . import auth
from .config import Settings, ws_url
from .fragments import fragment_reply

log = logging.getLogger("admeasy-desktop")


def _items(payload, keys: tuple[str, ...]) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def present_messages(rows: list) -> list[dict]:
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or row.get("sender") or "assistant")
        if role in ("human", "me"):
            role = "user"
        text = row.get("content")
        if text is None:
            text = row.get("text") or row.get("body") or ""
        if isinstance(text, list):
            text = " ".join(str(part.get("text") or "") for part in text if isinstance(part, dict))
        text = str(text or "").strip()
        if not text:
            continue
        if role == "assistant":
            for part in fragment_reply(text):
                out.append({"role": "assistant", "text": part, "id": row.get("id")})
        else:
            out.append({"role": "user" if role == "user" else role, "text": text, "id": row.get("id")})
    return out


class ChatBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.events: list[dict] = []
        self.conversation_id: str | None = None
        self.error = ""
        self.connected = False
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws = None
        self._reader: asyncio.Task | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ready = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="admeasy-chat", daemon=True)
        self._thread.start()
        ready.wait(5)

    def _push(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)
            if len(self.events) > 400:
                del self.events[:200]

    def drain(self) -> list[dict]:
        with self._lock:
            rows = list(self.events)
            self.events.clear()
            return rows

    def _token(self) -> str | None:
        try:
            refreshed = auth.refresh(self.settings.backend)
        except Exception:
            refreshed = None
        return refreshed or auth.load_secret("access_token")

    def history(self) -> dict:
        token = self._token()
        if not token:
            return {"messages": [], "conversation_id": None, "error": "sign in to load your chats"}
        headers = {"Authorization": f"Bearer {token}"}
        base = self.settings.backend.rstrip("/")
        try:
            listed = httpx.get(f"{base}/conversations", params={"limit": 30}, headers=headers, timeout=15)
        except Exception as exc:
            return {"messages": [], "conversation_id": self.conversation_id, "error": f"could not reach the backend: {exc}"}
        if listed.status_code == 401 and auth.refresh(self.settings.backend):
            return self.history()
        if listed.status_code != 200:
            return {"messages": [], "conversation_id": None, "error": f"conversations returned {listed.status_code}"}
        convos = _items(listed.json(), ("conversations", "items", "data"))
        conv_id = self.conversation_id
        if not conv_id and convos:
            first = convos[0]
            conv_id = str(first.get("id") or first.get("conversation_id") or "") or None
        messages: list = []
        if conv_id:
            try:
                got = httpx.get(
                    f"{base}/conversations/{conv_id}/messages",
                    params={"limit": 40},
                    headers=headers,
                    timeout=15,
                )
            except Exception as exc:
                return {"messages": [], "conversation_id": conv_id, "error": str(exc)}
            if got.status_code == 200:
                messages = _items(got.json(), ("messages", "items", "data"))
            else:
                return {"messages": [], "conversation_id": conv_id, "error": f"messages returned {got.status_code}"}
        self.conversation_id = conv_id
        return {"messages": present_messages(messages), "conversation_id": conv_id, "error": ""}

    def send(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.start()
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(self._send(text), self._loop)

    async def _send(self, text: str) -> None:
        token = self._token()
        if not token:
            self._push({"type": "error", "text": "sign in first"})
            return
        try:
            if self._ws is None:
                query = {"token": token}
                if self.conversation_id:
                    query["conversation_id"] = self.conversation_id
                url = ws_url(self.settings.backend, "/ws/session?" + urllib.parse.urlencode(query))
                self._ws = await websockets.connect(url, max_size=8 * 1024 * 1024, open_timeout=12)
                self.connected = True
                self.error = ""
                self._reader = asyncio.create_task(self._read())
            await self._ws.send(json.dumps({"type": "text", "text": text}))
        except Exception as exc:
            self.connected = False
            self._ws = None
            self.error = f"chat socket unavailable ({exc}). History still loads. The live backend needs /ws/session."
            self._push({"type": "error", "text": self.error})
            log.info("chat send failed: %s", exc)

    async def _read(self) -> None:
        assert self._ws is not None
        live = ""
        try:
            async for raw in self._ws:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "session" and event.get("conversation_id"):
                    self.conversation_id = str(event["conversation_id"])
                    self._push({"type": "session", "conversation_id": self.conversation_id})
                elif kind == "token":
                    live += str(event.get("text") or "")
                    self._push({"type": "live", "text": live})
                elif kind in ("done", "revision"):
                    final = str(event.get("text") or live)
                    self._push({"type": "final", "bubbles": fragment_reply(final)})
                    live = ""
                elif kind == "tool_call":
                    args = event.get("arguments") or {}
                    command = args.get("command") if isinstance(args, dict) else None
                    self._push({
                        "type": "note",
                        "text": str(event.get("name") or "working"),
                        "command": command,
                    })
                elif kind == "error":
                    self._push({"type": "error", "text": str(event.get("error") or "error")})
                elif kind == "approval_required":
                    self._push({"type": "note", "text": "I need a yes or no before I continue."})
                elif kind == "attachment":
                    self._push({"type": "note", "text": str(event.get("name") or "file"), "url": event.get("url")})
        except Exception as exc:
            self.connected = False
            self._ws = None
            self.error = str(exc)
            self._push({"type": "error", "text": f"chat disconnected: {exc}"})
