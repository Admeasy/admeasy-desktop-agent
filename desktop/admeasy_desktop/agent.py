"""The desktop agent: one outbound WSS tunnel to the Admeasy backend, one job at a time.

The phone talks to the cloud assistant; the assistant calls device_* tools; the backend relays each as a `task` over this
tunnel (the machine never opens an inbound port). Same wire protocol as the cloud VM agent
(hello / task / step / result / cancel_all), plus `permissions` and `approval_request` / `approval_result`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import random
import uuid

import websockets
from websockets.exceptions import ConnectionClosed

from . import VERSION, permissions
from .auth import load_secret
from .config import Settings, platform_name, ws_url
from .executors import screen, system
from .executors.browser import Browser
from .policy import judge
from .results import normalize as normalize_result

log = logging.getLogger("admeasy-desktop")
APPROVAL_WAIT_S = 120
# Job kinds the backend may send on /devices/tunnel (see admeasy-ai-assistant app/devices/tools.py).
JOB_KINDS = frozenset({"screenshot", "open", "browser", "shell", "files", "clipboard", "cua"})


class Agent:
    def __init__(self, settings: Settings):
        self.s = settings
        self.ws = None
        self.browser = Browser()
        self.task: asyncio.Task | None = None
        self.approvals: dict[str, asyncio.Future] = {}
        self.send_lock = asyncio.Lock()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.scaler = None
        self.status_cb = None  # UI hook: (online: bool, detail: str)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---------- wire ----------
    async def send(self, msg: dict) -> None:
        if self.ws is None:
            return
        async with self.send_lock:
            await self.ws.send(json.dumps(msg))

    def capabilities(self) -> dict:
        return {"screen": True, "mouse_keyboard": True, "browser": "chrome-playwright", "shell": True,
                "files": self.s.shared_folders, "clipboard": True, "approval_mode": self.s.approval_mode,
                "keep_awake": self.s.keep_awake}

    async def hello(self) -> None:
        await self.send({"type": "hello", "version": VERSION, "os_version": platform.platform(),
                         "capabilities": self.capabilities(), "permissions": permissions.wire_snapshot()})

    # ---------- jobs ----------
    async def step(self, jid: str, text: str) -> None:
        await self.send({"type": "step", "job_id": jid, "text": text[:300]})

    async def ask_user(self, jid: str, kind: str, verdict) -> bool:
        aid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.approvals[aid] = fut
        await self.send({"type": "approval_request", "approval_id": aid, "job_id": jid,
                         "action": str(kind)[:80], "summary": str(verdict.reason)[:400],
                         "risk": str(verdict.risk)[:20]})
        try:
            return bool(await asyncio.wait_for(fut, APPROVAL_WAIT_S + 5))
        except asyncio.TimeoutError:
            return False
        finally:
            self.approvals.pop(aid, None)

    async def run_job(self, job: dict) -> None:
        jid, kind, p = job["job_id"], job["kind"], job.get("params") or {}
        try:
            if self.s.paused:
                res = {"status": "denied", "error": "the user paused Admeasy on this computer"}
            else:
                v = judge(kind, p, self.s.approval_mode, self.s.shared_folders)
                if not v.allow:
                    res = {"status": "denied", "error": v.reason}
                elif v.ask and not await self.ask_user(jid, kind, v):
                    res = {"status": "denied", "error": "the user did not approve this action"}
                else:
                    miss = permissions.missing(permissions.wire_snapshot()) if kind in ("cua", "screenshot") else []
                    res = ({"status": "needs_permission", "error": "grant in System Settings: " + ", ".join(miss)}
                           if miss else normalize_result(kind, await asyncio.wait_for(
                               self.dispatch(jid, kind, p), job.get("timeout_s", 300))))
        except asyncio.CancelledError:
            res = {"status": "cancelled", "error": "stopped by the user"}
        except asyncio.TimeoutError:
            res = {"status": "failed", "error": "timed out"}
        except Exception as e:
            log.exception("job %s", jid)
            res = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        res = normalize_result(kind, res)
        log.info("job %s %s -> %s", jid, kind, res.get("status"))
        await self.send({"type": "result", "job_id": jid, **res})

    async def dispatch(self, jid: str, kind: str, p: dict) -> dict:
        if kind not in JOB_KINDS:
            return {"status": "failed", "error": f"unknown kind {kind}"}
        loop = asyncio.get_running_loop()
        if kind == "screenshot":
            return {"status": "done", "result": await loop.run_in_executor(None, screen.screenshot)}
        if kind == "cua":
            a = p.get("action") or {}
            t = a.get("type")
            if t == "done":
                return {"status": "done", "result": {"answer": str(a.get("answer") or "")}}
            if t == "needs_login":
                return {"status": "needs_login", "error": "sign-in or captcha required on screen"}
            if t not in (None, "screenshot"):
                await self.step(jid, f"{t} {a.get('text', '')[:40]}")
                await loop.run_in_executor(None, screen.act, a, self.scaler)
                await asyncio.sleep(0.8)
            shot = await loop.run_in_executor(None, screen.screenshot)
            self.scaler = screen.Scaler(tuple(screen._pg().size()), tuple(shot["size"]))
            return {"status": "done", "result": shot}
        if kind == "browser":
            await self.step(jid, f"browser {p.get('op')} {p.get('url', '')[:80]}")
            return await self.browser.run(p)
        if kind == "shell":
            await self.step(jid, "$ " + str(p.get("command"))[:200])
            return await system.shell(p)
        if kind == "open":
            await self.step(jid, f"open {p.get('target')}")
            return await loop.run_in_executor(None, system.open_target, p)
        if kind == "files":
            return await loop.run_in_executor(None, system.files, p, self.s.shared_folders)
        if kind == "clipboard":
            return await loop.run_in_executor(None, system.clipboard, p)
        return {"status": "failed", "error": f"unhandled kind {kind}"}

    async def worker(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                self.task = asyncio.create_task(self.run_job(job))
                await self.task
            except asyncio.CancelledError:
                pass
            finally:
                self.task = None
                self.queue.task_done()

    async def _emit_cancelled(self, job_id: str) -> None:
        await self.send({"type": "result", "job_id": job_id, "status": "cancelled", "error": "stopped by the user"})

    def cancel_all(self) -> None:
        queued = []
        while not self.queue.empty():
            queued.append(self.queue.get_nowait())
        loop = self._loop
        for job in queued:
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(self._emit_cancelled(job["job_id"]), loop)
        if self.task and not self.task.done():
            self.task.cancel()
        for f in self.approvals.values():
            if not f.done():
                f.set_result(False)

    # ---------- tunnel ----------
    async def tunnel(self) -> None:
        self._loop = asyncio.get_running_loop()
        asyncio.create_task(self.worker())
        backoff = 1
        while True:
            dev, tok = load_secret("device_id"), load_secret("device_token")
            if not (dev and tok):
                await asyncio.sleep(2)  # not signed in yet: the UI enrols this computer
                continue
            try:
                async with websockets.connect(ws_url(self.s.backend, "/devices/tunnel"), additional_headers={
                        "Authorization": f"Bearer {tok}", "X-Device-Id": dev}, ping_interval=20,
                        max_size=16 * 1024 * 1024) as ws:
                    self.ws, backoff = ws, 1
                    await self.hello()
                    self._notify(True, "connected")
                    watcher = asyncio.create_task(self._watch_permissions())
                    try:
                        async for raw in ws:
                            m = json.loads(raw)
                            t = m.get("type")
                            if t == "task":
                                await self.queue.put(m)
                            elif t == "approval_result":
                                f = self.approvals.get(m.get("approval_id"))
                                if f and not f.done():
                                    f.set_result(bool(m.get("allow")))
                            elif t == "cancel_all":
                                self.cancel_all()
                    finally:
                        watcher.cancel()
            except websockets.exceptions.InvalidStatus as e:
                code = getattr(getattr(e, "response", None), "status_code", 0)
                if code == 503:
                    self._notify(False, "devices disabled on backend (DEVICES_ENABLED)")
                    await asyncio.sleep(60)
                elif code in (401, 403):
                    from .auth import clear_device_secrets
                    clear_device_secrets()
                    self._notify(False, "sign in again (device token invalid or revoked)")
                    await asyncio.sleep(30)
            except ConnectionClosed as e:
                log.warning("tunnel closed: %s", e)
            except Exception as e:
                log.warning("tunnel down: %s", e)
            self.ws = None
            self._notify(False, "offline, retrying")
            await asyncio.sleep(min(backoff, 30) + random.uniform(0, 0.5))
            backoff = min(backoff * 2, 30)

    async def _watch_permissions(self) -> None:
        last = None
        while True:
            cur = permissions.wire_snapshot()
            if cur != last:
                await self.send({"type": "permissions", "permissions": cur})
                last = cur
            await asyncio.sleep(30)

    def _notify(self, online: bool, detail: str) -> None:
        if self.status_cb:
            self.status_cb(online, detail)
