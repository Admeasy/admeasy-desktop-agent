"""The desktop agent: one outbound WSS tunnel to the Admeasy backend, one job at a time."""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import random
import sys
import uuid

import websockets
from websockets.exceptions import ConnectionClosed

from . import VERSION, permissions
from .auth import load_secret
from .config import Settings, platform_name, ws_url
from .executors import app_exec, cli_exec, comms_exec, ide_exec, mail_exec, messages_exec, screen, system, terminal_exec
from .executors.browser import Browser
from .executors import whatsapp_exec
from .failure_detect import analyze as detect_failure
from .job_kinds import JOB_KINDS, TOOL_MANIFEST
from .job_store import JobStore
from .policy import judge
from .results import normalize as normalize_result
from .signin_handoff import run as signin_run
from .surface_status import collect as surface_collect
from .system_hooks import keep_awake
from . import cursor_overlay
from .bridge_server import start as start_bridge_server
from .browser_bridge import extension_status

log = logging.getLogger("admeasy-desktop")
APPROVAL_WAIT_S = 120


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
        self.status_cb = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.store = JobStore()
        self.objective_id: str | None = None
        self.objective_step: str = ""
        self.rows_so_far: int = 0
        self.blocker: str = ""
        self._objective_jobs: int = 0

    async def send(self, msg: dict) -> None:
        async with self.send_lock:
            if self.ws is None:
                if msg.get("type") == "result":
                    self.store.buffer_result(msg)
                return
            await self.ws.send(json.dumps(msg))

    def capabilities(self) -> dict:
        return {
            "screen": True,
            "mouse_keyboard": True,
            "browser": self.s.browser_automation,
            "browser_modes": ["default_first", "playwright_profile", "extension_bridge"],
            "playwright_requires": "params.force_playwright or ADMEASY_PLAYWRIGHT=1",
            "native_apps": True,
            "agent_cursor_overlay": self.s.show_agent_cursor,
            "objectives": {"echo_objective_id": True},
            "set_of_mark": True,
            "ax_tree": sys.platform in ("darwin", "win32"),
            "extension_bridge": extension_status(),
            "shell": True,
            "terminal": True,
            "cli_profiles": ["claude", "gemini", "cursor", "git"],
            "files": self.s.shared_folders,
            "clipboard": True,
            "ide": ["cursor", "vscode"],
            "messaging": True,
            "approval_mode": self.s.approval_mode,
            "keep_awake": self.s.keep_awake,
            "job_kinds": sorted(JOB_KINDS),
            "tools": TOOL_MANIFEST,
            "contract_version": "0.4.0",
        }

    async def hello(self) -> None:
        await self.send(
            {
                "type": "hello",
                "version": VERSION,
                "os_version": platform.platform(),
                "capabilities": self.capabilities(),
                "permissions": permissions.wire_snapshot(),
            }
        )
        for pending in self.store.pop_pending():
            await self.send(pending)

    async def step(self, jid: str, text: str, objective_id: str | None = None) -> None:
        msg = {"type": "step", "job_id": jid, "text": text[:300]}
        oid = objective_id or self.objective_id
        if oid:
            msg["objective_id"] = oid
        await self.send(msg)
        self.objective_step = text[:120]

    async def ask_user(self, jid: str, kind: str, verdict) -> bool:
        aid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.approvals[aid] = fut
        await self.send(
            {
                "type": "approval_request",
                "approval_id": aid,
                "job_id": jid,
                "action": str(kind)[:80],
                "summary": str(verdict.reason)[:400],
                "risk": str(verdict.risk)[:20],
            }
        )
        try:
            return bool(await asyncio.wait_for(fut, APPROVAL_WAIT_S + 5))
        except asyncio.TimeoutError:
            return False
        finally:
            self.approvals.pop(aid, None)

    def _track_objective(self, params: dict, on: bool) -> None:
        oid = params.get("objective_id")
        if oid:
            self.objective_id = str(oid)
        if on:
            self._objective_jobs += 1
            keep_awake(True)
        else:
            self._objective_jobs = max(0, self._objective_jobs - 1)
            if self._objective_jobs == 0:
                keep_awake(False)
                if not oid:
                    self.objective_id = None

    async def run_job(self, job: dict) -> None:
        jid, kind, p = job["job_id"], job["kind"], job.get("params") or {}
        idem = str(p.get("idempotency_key") or "")
        cached = self.store.get_idempotent(idem)
        if cached:
            await self.send({"type": "result", "job_id": jid, **cached})
            return
        self._track_objective(p, True)
        try:
            if self.s.paused:
                res = {"status": "blocked", "error": "the user paused Admeasy on this computer"}
            else:
                v = judge(kind, p, self.s.approval_mode, self.s.shared_folders)
                if not v.allow:
                    res = {"status": "blocked", "error": v.reason}
                elif v.ask and not await self.ask_user(jid, kind, v):
                    res = {"status": "blocked", "error": "the user did not approve this action"}
                else:
                    snap = permissions.wire_snapshot()
                    miss = permissions.missing_for_kind(kind, p, snap)
                    res = (
                        {
                            "status": "permission_missing",
                            "error": "grant in System Settings: " + ", ".join(miss),
                            "result": {"permissions_missing": miss, "reason": "permission_missing"},
                        }
                        if miss
                        else normalize_result(
                            kind,
                            await asyncio.wait_for(self.dispatch(jid, kind, p), job.get("timeout_s", 300)),
                        )
                    )
        except asyncio.CancelledError:
            res = {"status": "cancelled", "error": "stopped by the user"}
        except asyncio.TimeoutError:
            res = {"status": "timeout", "error": "timed out", "result": {"reason": "job_timeout"}}
        except Exception as e:
            log.exception("job %s", jid)
            res = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        finally:
            self._track_objective(p, False)
        res = normalize_result(kind, res)
        res = self._attach_objective(p, res)
        res = self._attach_evidence(jid, res)
        if idem:
            self.store.put_idempotent(idem, res)
        log.info("job %s %s -> %s", jid, kind, res.get("status"))
        await self.send({"type": "result", "job_id": jid, **res})

    @staticmethod
    def _attach_evidence(jid: str, res: dict) -> dict:
        body = res.get("result")
        if isinstance(body, dict) and body.get("screenshot_b64"):
            ev = dict(body.get("evidence") or {})
            ev["screenshot_ref"] = jid
            body["evidence"] = ev
            res["result"] = body
        return res

    @staticmethod
    def _attach_objective(params: dict, res: dict) -> dict:
        oid = params.get("objective_id")
        if not oid:
            return res
        out = dict(res)
        body = dict(out.get("result") or {})
        body["objective_id"] = oid
        if params.get("objective_status"):
            body["objective_status"] = params.get("objective_status")
        out["result"] = body
        return out

    async def dispatch(self, jid: str, kind: str, p: dict) -> dict:
        if kind not in JOB_KINDS:
            return {"status": "error", "error": f"unknown kind {kind}"}
        loop = asyncio.get_running_loop()

        async def on_output(chunk: str) -> None:
            await self.step(jid, chunk, p.get("objective_id"))

        if kind == "status":
            return {"status": "ok", "result": surface_collect(p)}
        if kind == "signin":
            return await signin_run(p)
        if kind == "screenshot":
            return {"status": "ok", "result": await loop.run_in_executor(None, screen.screenshot)}
        if kind == "cua":
            if self.s.show_agent_cursor:
                cursor_overlay.ensure_started()
            a = p.get("action") or {}
            t = a.get("type")
            if t == "done":
                return {"status": "ok", "result": {"answer": str(a.get("answer") or "")}}
            if t == "needs_login":
                return {"status": "needs_login", "error": "sign-in required", "result": {"reason": "needs_login"}}
            if t not in (None, "screenshot"):
                await self.step(jid, f"{t} {a.get('text', '')[:40]}", p.get("objective_id"))
                await loop.run_in_executor(None, screen.act, a, self.scaler)
                await asyncio.sleep(0.8)
            shot = await loop.run_in_executor(None, screen.screenshot)
            self.scaler = screen.Scaler(tuple(screen._pg().size()), tuple(shot["size"]))
            hints = p.get("skill_hints") or []
            fail = detect_failure(shot.get("ax_tree") or [], skill_hints=hints)
            if fail and fail.get("status") == "captcha":
                return {"status": "captcha", "error": fail.get("reason"), "result": shot}
            if fail:
                return {"status": fail.get("status", "needs_human"), "error": fail.get("reason"), "result": shot}
            return {"status": "ok", "result": shot}
        if kind == "browser":
            await self.step(jid, f"browser {p.get('op')} {p.get('url', '')[:80]}", p.get("objective_id"))
            return await self.browser.run(p)
        if kind == "shell":
            await self.step(jid, "$ " + str(p.get("command"))[:200], p.get("objective_id"))
            return await system.shell(p)
        if kind == "terminal":
            return await terminal_exec.run(p, on_output=on_output)
        if kind == "cli":
            return await cli_exec.run(p, on_output=on_output)
        if kind == "app":
            return await app_exec.run(p, on_output=on_output)
        if kind == "ide":
            return await loop.run_in_executor(None, ide_exec.run, p)
        if kind == "whatsapp":
            return await whatsapp_exec.run(p)
        if kind == "messages":
            return await loop.run_in_executor(None, messages_exec.run, p)
        if kind == "comms":
            return await loop.run_in_executor(None, comms_exec.run, p)
        if kind == "mail":
            return await loop.run_in_executor(None, mail_exec.run, p)
        if kind == "open":
            await self.step(jid, f"open {p.get('target')}", p.get("objective_id"))
            out = await loop.run_in_executor(None, system.open_target, p)
            if out.get("status") == "done":
                out["status"] = "ok"
            return out
        if kind == "files":
            out = await loop.run_in_executor(None, system.files, p, self.s.shared_folders)
            if out.get("status") == "done":
                out["status"] = "ok"
            if p.get("op") == "append_rows" and out.get("status") == "ok":
                self.rows_so_far += int((out.get("result") or {}).get("appended") or 0)
            return out
        if kind == "clipboard":
            out = await loop.run_in_executor(None, system.clipboard, p)
            if out.get("status") == "done":
                out["status"] = "ok"
            return out
        return {"status": "error", "error": f"unhandled kind {kind}"}

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

    async def tunnel(self) -> None:
        self._loop = asyncio.get_running_loop()
        start_bridge_server()
        if self.s.show_agent_cursor:
            cursor_overlay.set_enabled(True)
            cursor_overlay.ensure_started()
        asyncio.create_task(self.worker())
        backoff = 1
        while True:
            dev, tok = load_secret("device_id"), load_secret("device_token")
            if not (dev and tok):
                await asyncio.sleep(2)
                continue
            try:
                async with websockets.connect(
                    ws_url(self.s.backend, "/devices/tunnel"),
                    additional_headers={"Authorization": f"Bearer {tok}", "X-Device-Id": dev},
                    ping_interval=20,
                    max_size=16 * 1024 * 1024,
                ) as ws:
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
