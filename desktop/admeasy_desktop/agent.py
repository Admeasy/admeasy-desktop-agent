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
from .entitlements import (
    COMPUTER_USE_ACTION,
    EXEMPT_KINDS,
    UPGRADE_URL,
    EntitlementsClient,
    EntitlementsError,
    feature_message,
    limit_message,
    required_features,
)
from .default_browser import default_browser
from .executors import app_exec, cli_exec, comms_exec, ide_exec, mail_exec, messages_exec, screen, system, terminal_exec
from .executors.browser import Browser
from .executors import whatsapp_exec
from .failure_detect import analyze as detect_failure
from .job_kinds import JOB_KINDS, TOOL_MANIFEST
from .job_limits import job_idempotency_key, job_timeout_s
from .job_store import JobStore
from .policy import judge
from .safety import audit, folder_roots, gate_job, toggles
from .results import normalize as normalize_result
from .signin_handoff import run as signin_run
from .surface_status import collect as surface_collect
from .system_hooks import keep_awake
from . import agent_edge_overlay, cursor_overlay
from .agent_session import AgentSession

log = logging.getLogger("admeasy-desktop")
APPROVAL_WAIT_S = 300


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
        self.entitlements = EntitlementsClient(settings.backend)
        self._snap = None
        self.session = AgentSession()
        self._edge_task: asyncio.Task | None = None
        self.feed: list[dict] = []
        self.local_approvals: dict[str, dict] = {}

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
            "browser_modes": ["default_first", "playwright_profile"],
            "playwright_requires": "params.force_playwright or ADMEASY_PLAYWRIGHT=1",
            "native_apps": True,
            "agent_cursor_overlay": self.s.show_agent_cursor and cursor_overlay.is_available(),
            "agent_edge_border": self.s.show_agent_edge_border and agent_edge_overlay.is_available(),
            "objectives": {"echo_objective_id": True},
            "set_of_mark": True,
            "ax_tree": sys.platform in ("darwin", "win32"),
            "shell": True,
            "terminal": True,
            "cli_profiles": self._cli_profiles(),
            "files": folder_roots(self.s),
            "capability_toggles": toggles(self.s),
            "clipboard": True,
            "ide": ["cursor", "vscode"],
            "messaging": True,
            "approval_mode": self.s.approval_mode,
            "keep_awake": self.s.keep_awake,
            "job_kinds": sorted(JOB_KINDS),
            "tools": TOOL_MANIFEST,
            "contract_version": "0.5.0",
            "default_browser": default_browser(),
            "plan": self._plan_caps(),
        }

    def _cli_profiles(self) -> list[str]:
        profiles = ["claude", "gemini", "cursor", "git"]
        snap = self._snap
        if snap is None or not snap.allows("claude"):
            profiles = [p for p in profiles if p != "claude"]
        return profiles

    def _plan_caps(self) -> dict:
        snap = self._snap
        if snap is None:
            return {
                "family": None,
                "models": ["sarvam", "groq"],
                "features": {
                    "local_machine": True,
                    "virtual_machine": False,
                    "claude": False,
                    "vision": False,
                    "deep_agents": False,
                },
                "vision": False,
            }
        return {
            "family": snap.plan_family or snap.plan or None,
            "models": list(snap.models),
            "features": dict(snap.features),
            "vision": snap.allows("vision"),
        }

    def refresh_entitlements(self) -> None:
        try:
            self._snap = self.entitlements.me()
        except EntitlementsError as exc:
            log.info("entitlements: %s", exc)

    async def hello(self) -> None:
        self.refresh_entitlements()
        await self.send(
            {
                "type": "hello",
                "version": VERSION,
                "os_version": platform.platform(),
                "capabilities": self.capabilities(),
                "permissions": permissions.wire_snapshot(),
                "contract_version": self.capabilities().get("contract_version"),
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
        self.feed.append({"role": "assistant", "text": text[:300], "kind": "step"})
        if len(self.feed) > 200:
            del self.feed[:100]
        self.session.heartbeat()
        self._sync_edge_border()

    async def ask_user(self, jid: str, kind: str, verdict) -> bool:
        aid = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.approvals[aid] = fut
        self.local_approvals[aid] = {
            "id": aid,
            "job_id": jid,
            "action": str(kind)[:80],
            "summary": str(verdict.reason)[:400],
            "risk": str(verdict.risk)[:20],
        }
        self.session.set_approval_wait(True)
        self._sync_edge_border()
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
            self.local_approvals.pop(aid, None)
            self.session.set_approval_wait(False)
            self._sync_edge_border()

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
        self.session.track_objective(on)

    def _sync_edge_border(self) -> None:
        if not self.s.show_agent_edge_border or not agent_edge_overlay.is_available():
            agent_edge_overlay.hide()
            return
        agent_edge_overlay.set_enabled(True)
        agent_edge_overlay.ensure_started()
        agent_edge_overlay.set_active(self.session.active, pulse=self.session.pulse)

    async def _edge_border_loop(self) -> None:
        while True:
            self._sync_edge_border()
            await asyncio.sleep(0.25)

    async def run_job(self, job: dict) -> None:
        jid, kind, p = job["job_id"], job["kind"], job.get("params") or {}
        # Every job gets a key: the backend's idempotency_key, else its job_id. A job re-delivered after a reconnect
        # returns the stored result instead of clicking/typing a second time; one already running is not started twice.
        idem = job_idempotency_key(jid, p)
        cached = self.store.get_idempotent(idem)
        if cached:
            await self.send({"type": "result", "job_id": jid, **cached})
            return
        inflight = self.__dict__.setdefault("_inflight", set())
        if idem in inflight:
            log.info("job %s %s already running; duplicate ignored", jid, kind)
            return
        inflight.add(idem)
        try:
            await self._run_job(job, jid, kind, p, idem)
        finally:
            inflight.discard(idem)

    async def _run_job(self, job: dict, jid: str, kind: str, p: dict, idem: str) -> None:
        self._track_objective(p, True)
        self.session.job_started(kind)
        self._sync_edge_border()
        try:
            if self.s.paused:
                res = {"status": "blocked", "error": "the user paused Admeasy on this computer"}
            elif (gated := gate_job(self.s, kind, p)):
                res = gated
            else:
                autonomous = bool(p.get("autonomous") or p.get("scheduled") or p.get("reminder_id"))
                v = judge(
                    kind, p, self.s.approval_mode, folder_roots(self.s),
                    allowlist=getattr(self.s, "command_allowlist", None),
                    blocklist=getattr(self.s, "command_blocklist", None),
                    autonomous=autonomous,
                )
                if not v.allow:
                    res = {"status": "blocked", "error": v.reason}
                elif v.ask and not await self.ask_user(jid, kind, v):
                    res = {"status": "blocked", "error": "the user did not approve this action"}
                elif (blocked := self._entitlement_block(kind, p)):
                    res = blocked
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
                            await asyncio.wait_for(self.dispatch(jid, kind, p), job_timeout_s(kind, job, p)),
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
            self.session.job_finished(kind)
            self._track_objective(p, False)
            self._sync_edge_border()
        res = normalize_result(kind, res)
        if res.get("status") == "ok":
            self.blocker = ""
        res = self._attach_objective(p, res)
        res = self._attach_evidence(jid, res)
        self.store.put_idempotent(idem, res)
        log.info("job %s %s -> %s", jid, kind, res.get("status"))
        summary = str(p.get("command") or p.get("target") or p.get("op") or kind)[:180]
        audit({
            "kind": kind,
            "status": res.get("status"),
            "summary": summary,
            "error": str(res.get("error") or "")[:180],
            "autonomous": bool(p.get("autonomous") or p.get("scheduled") or p.get("reminder_id")),
        })
        await self.send({"type": "result", "job_id": jid, **res})

    def _entitlement_block(self, kind: str, params: dict) -> dict | None:
        """Stop a computer-use job the plan does not allow. Exempt jobs never call the API."""
        if kind in EXEMPT_KINDS:
            return None
        try:
            snap = self.entitlements.me()
        except EntitlementsError as exc:
            return {
                "status": "error",
                "error": f"Couldn't check your plan ({exc}). Try again in a moment.",
                "result": {"reason": "entitlements_unavailable", "upgrade_url": UPGRADE_URL},
            }
        self._snap = snap
        if not snap.invited:
            message = (
                "This computer needs an invited Admeasy account. "
                f"Enter a code in the Admeasy window, then sign in. {UPGRADE_URL}"
            )
            self.blocker = message
            return {
                "status": "blocked",
                "error": message,
                "result": {"reason": "invite_required", "upgrade_url": UPGRADE_URL},
            }
        if not snap.allows("local_machine"):
            message = feature_message("local_machine", snap)
            self.blocker = message
            return {
                "status": "blocked",
                "error": message,
                "result": {"reason": "plan_feature", "feature": "local_machine", "upgrade_url": UPGRADE_URL},
            }
        for feature in sorted(required_features(kind, params)):
            if not snap.allows(feature):
                message = feature_message(feature, snap)
                self.blocker = message
                return {
                    "status": "blocked",
                    "error": message,
                    "result": {"reason": "plan_feature", "feature": feature, "upgrade_url": UPGRADE_URL},
                }
        try:
            decision = self.entitlements.usage_check(COMPUTER_USE_ACTION)
        except EntitlementsError as exc:
            return {
                "status": "error",
                "error": f"Couldn't check this week's usage ({exc}). Try again in a moment.",
                "result": {"reason": "entitlements_unavailable", "upgrade_url": UPGRADE_URL},
            }
        if decision.allowed:
            return None
        message = limit_message(decision, snap)
        self.blocker = message
        status = "rate_limited" if decision.is_limit else "blocked"
        return {
            "status": status,
            "error": message,
            "result": {
                "reason": decision.code or "plan_limit",
                "upgrade_url": decision.upgrade_url or UPGRADE_URL,
                "remaining": decision.remaining,
                "limit": decision.limit,
            },
        }

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
            a = p.get("action") or {}
            t = a.get("type")
            if t == "done":
                return {"status": "ok", "result": {"answer": str(a.get("answer") or "")}}
            if t == "needs_login":
                return {"status": "needs_login", "error": "sign-in required", "result": {"reason": "needs_login"}}
            if self.scaler is None and t not in (None, "screenshot", "wait"):
                prime = await loop.run_in_executor(None, screen.screenshot)
                self.scaler = screen.scaler_for(prime)
            if t not in (None, "screenshot", "wait") and sys.platform == "darwin":
                from . import input_darwin

                input_darwin.log_identity(f"job={jid} action={t}")
                if not input_darwin.accessibility_trusted():
                    return {
                        "status": "permission_missing",
                        "error": (
                            "grant Accessibility to the app running Admeasy "
                            "(Admeasy.app, Terminal, or your IDE) — clicks and typing will not work until then"
                        ),
                        "result": {"permissions_missing": ["accessibility"], "reason": "permission_missing"},
                    }
            act_report: dict = {}
            if t not in (None, "screenshot"):
                label = t
                if a.get("element_id") is not None:
                    label = f"{t} element_id={a.get('element_id')}"
                elif a.get("x") is not None:
                    label = f"{t} @ {int(a.get('x'))},{int(a.get('y'))}"
                await self.step(jid, label[:300], p.get("objective_id"))
                try:
                    act_report = await loop.run_in_executor(None, screen.act, a, self.scaler)
                except ValueError as e:
                    return {"status": "error", "error": str(e), "result": {"reason": "bad_action"}}
                except RuntimeError as e:
                    return {
                        "status": "permission_missing",
                        "error": str(e),
                        "result": {"permissions_missing": ["accessibility"], "reason": "click_failed"},
                    }
                from .ui_settle import wait_for_settle

                await loop.run_in_executor(
                    None,
                    lambda: wait_for_settle(
                        screen.screenshot,
                        max_wait_s=max(screen.settle_seconds(a), 0.5),
                    ),
                )
            shot = await loop.run_in_executor(None, screen.screenshot)
            self.scaler = screen.scaler_for(shot)
            if act_report:
                shot["last_action"] = act_report
            shot.setdefault("elements", [])
            await self.step(
                jid,
                f"screenshot {shot['size'][0]}x{shot['size'][1]} ({len(shot.get('elements') or [])} marks)",
                p.get("objective_id"),
            )
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
            out = await loop.run_in_executor(None, system.files, p, folder_roots(self.s))
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
            self.session.job_dequeued()
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
        self.session.reset()
        self._sync_edge_border()
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
        if self.s.show_agent_cursor and cursor_overlay.is_available():
            cursor_overlay.set_enabled(True)
            cursor_overlay.ensure_started()
        if self.s.show_agent_edge_border and agent_edge_overlay.is_available():
            agent_edge_overlay.set_enabled(True)
            agent_edge_overlay.ensure_started()
        self._edge_task = asyncio.create_task(self._edge_border_loop())
        asyncio.create_task(self.worker())
        backoff = 1
        while True:
            dev, tok = load_secret("device_id"), load_secret("device_token")
            if not (dev and tok):
                await asyncio.sleep(2)
                continue
            allowed, why = self._tunnel_allowed()
            if not allowed:
                self._notify(False, why)
                await asyncio.sleep(5)
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
                                self.session.job_enqueued()
                                self._sync_edge_border()
                                await self.queue.put(m)
                            elif t == "approval_result":
                                f = self.approvals.get(m.get("approval_id"))
                                if f and not f.done():
                                    f.set_result(bool(m.get("allow")))
                            elif t == "cancel_all":
                                self.cancel_all()
                            elif t == "reminder" and toggles(self.s).get("notify", True):
                                from .notify import toast
                                text = str(m.get("text") or "reminder")
                                toast("Admeasy", text)
                                self.feed.append({"role": "assistant", "text": text, "kind": "reminder"})
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

    def _tunnel_allowed(self) -> tuple[bool, str]:
        try:
            snap = self.entitlements.me()
        except EntitlementsError as exc:
            return False, f"couldn't check your invite ({exc})"
        self._snap = snap
        if not snap.invited:
            return False, "invite required — enter a code, then sign in with Google"
        if not snap.allows("local_machine"):
            return False, feature_message("local_machine", snap)
        return True, ""

    def _notify(self, online: bool, detail: str) -> None:
        if self.status_cb:
            self.status_cb(online, detail)
