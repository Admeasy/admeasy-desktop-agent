"""Device registry + job relay for the Admeasy desktop agent (.dmg / .exe).

Same shape as workers/service.py (outbound WSS tunnel, job queue in Postgres), but keyed by device_id and not by user.
One user can own many devices; the LLM picks one with the `device` argument (id or a name the user gave it).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_devices (
  id uuid PRIMARY KEY, user_id text NOT NULL, name text NOT NULL, platform text NOT NULL,
  os_version text, agent_version text, token_hash text NOT NULL,
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb, permissions jsonb NOT NULL DEFAULT '{}'::jsonb,
  state text NOT NULL DEFAULT 'offline', created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz, revoked_at timestamptz);
CREATE INDEX IF NOT EXISTS user_devices_user_idx ON user_devices (user_id) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS device_jobs (
  id uuid PRIMARY KEY, user_id text NOT NULL, device_id uuid NOT NULL, conversation_id text,
  kind text NOT NULL, params jsonb NOT NULL, status text NOT NULL DEFAULT 'queued', result jsonb, error text,
  steps jsonb NOT NULL DEFAULT '[]'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz, finished_at timestamptz);
CREATE INDEX IF NOT EXISTS device_jobs_dev_idx ON device_jobs (device_id, created_at DESC);
"""
TERMINAL = {"done", "failed", "needs_login", "needs_human", "needs_permission", "denied", "cancelled"}
APPROVAL_TTL_S = 120


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class DeviceTunnel:
    ws: object
    device_id: str
    user_id: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, msg: dict) -> None:
        async with self.lock:
            await self.ws.send_text(json.dumps(msg))


class DeviceService:
    def __init__(self, pool, activity=None):
        self.pool, self.activity = pool, activity
        self.tunnels: dict[str, DeviceTunnel] = {}  # device_id -> tunnel
        self.waiters: dict[str, asyncio.Event] = {}
        self.on_approval = None  # async (user_id, approval_id, info) -> None; main wires it to push
        self._approvals: dict[str, dict] = {}  # approval id -> {user_id, device_id, summary, fut}

    async def setup(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute(SCHEMA)

    # ---------- enrolment: the signed-in app registers itself, the user's JWT proves who they are ----------
    async def register(self, user_id: str, name: str, platform: str, os_version: str = "",
                       capabilities: dict | None = None) -> dict:
        did, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO user_devices (id, user_id, name, platform, os_version, token_hash, capabilities)
                VALUES ($1::uuid,$2,$3,$4,$5,$6,$7::jsonb)""", did, user_id, name[:80], platform[:20],
                            os_version[:80], _h(token), json.dumps(capabilities or {}))
        return {"device_id": did, "device_token": token}  # token is shown once, only its hash is stored

    async def revoke(self, user_id: str, device_id: str) -> bool:
        async with self.pool.acquire() as c:
            n = await c.fetchval("""UPDATE user_devices SET revoked_at=now(), state='offline'
                WHERE id=$1::uuid AND user_id=$2 AND revoked_at IS NULL RETURNING 1""", device_id, user_id)
        t = self.tunnels.pop(device_id, None)
        if t:
            try:
                await t.ws.close(code=4403)
            except Exception:
                pass
        return bool(n)

    async def rename(self, user_id: str, device_id: str, name: str) -> bool:
        async with self.pool.acquire() as c:
            return bool(await c.fetchval("UPDATE user_devices SET name=$3 WHERE id=$1::uuid AND user_id=$2 "
                                         "AND revoked_at IS NULL RETURNING 1", device_id, user_id, name[:80]))

    async def list(self, user_id: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("""SELECT id::text, name, platform, os_version, agent_version, capabilities, permissions,
                last_seen_at FROM user_devices WHERE user_id=$1 AND revoked_at IS NULL ORDER BY created_at""", user_id)
        out = []
        for r in rows:
            d = dict(r)
            d["online"] = d["id"] in self.tunnels
            d["last_seen_at"] = d["last_seen_at"].isoformat() if d["last_seen_at"] else None
            for k in ("capabilities", "permissions"):
                d[k] = json.loads(d[k]) if isinstance(d[k], str) else d[k]
            out.append(d)
        return out

    async def pick(self, user_id: str, device: str | None) -> dict:
        """Resolve the device the user means. Exact id, then name match; with one device, that device."""
        devices = await self.list(user_id)
        if not devices:
            return {"error": "no computer is connected to this account. Install the Admeasy desktop app and sign in "
                             "with the same Google account."}
        if device:
            want = device.strip().lower()
            hit = [d for d in devices if d["id"] == device or d["name"].lower() == want] or \
                  [d for d in devices if want in d["name"].lower() or want == d["platform"].lower()]
            if len(hit) == 1:
                return hit[0]
            if len(hit) > 1:
                return {"error": "more than one device matches", "devices": _brief(hit)}
            return {"error": "no device with that name", "devices": _brief(devices)}
        online = [d for d in devices if d["online"]]
        if len(devices) == 1:
            return devices[0]
        if len(online) == 1:
            return online[0]
        return {"error": "several computers are connected, ask which one", "devices": _brief(devices)}

    # ---------- tunnel ----------
    async def authenticate(self, device_id: str, token: str) -> dict | None:
        try:
            uuid.UUID(device_id)
        except ValueError:
            return None
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT user_id, token_hash, name FROM user_devices WHERE id=$1::uuid "
                                 "AND revoked_at IS NULL", device_id)
        if r and hmac.compare_digest(r["token_hash"], _h(token)):
            return {"user_id": r["user_id"], "name": r["name"]}
        return None

    async def on_tunnel(self, device_id: str, user_id: str, ws) -> None:
        old = self.tunnels.get(device_id)
        t = DeviceTunnel(ws=ws, device_id=device_id, user_id=user_id)
        self.tunnels[device_id] = t
        if old:
            try:
                await old.ws.close()
            except Exception:
                pass
        await self._dev(device_id, state="online", last_seen_at="now()")
        try:
            async with self.pool.acquire() as c:  # jobs running on a dropped connection go back to the queue
                await c.execute("UPDATE device_jobs SET status='queued' WHERE device_id=$1::uuid AND status='running'",
                                device_id)
            await self._pump(device_id)
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                m = json.loads(msg.get("text") or "{}")
                typ = m.get("type")
                if typ == "hello":
                    async with self.pool.acquire() as c:
                        await c.execute("""UPDATE user_devices SET agent_version=$2, os_version=COALESCE($3, os_version),
                            capabilities=$4::jsonb, permissions=$5::jsonb WHERE id=$1::uuid""", device_id,
                                        str(m.get("version")), m.get("os_version"),
                                        json.dumps(m.get("capabilities") or {}), json.dumps(m.get("permissions") or {}))
                elif typ == "permissions":
                    async with self.pool.acquire() as c:
                        await c.execute("UPDATE user_devices SET permissions=$2::jsonb WHERE id=$1::uuid",
                                        device_id, json.dumps(m.get("permissions") or {}))
                elif typ == "approval_request":
                    asyncio.create_task(self._ask_user(t, m))
                elif typ == "step":
                    async with self.pool.acquire() as c:
                        await c.execute("""UPDATE device_jobs SET steps = steps || jsonb_build_array(jsonb_build_object(
                            't', now(), 'text', $2::text)) WHERE id=$1::uuid""", m["job_id"], m.get("text", ""))
                elif typ == "result":
                    await self._finish(m["job_id"], m.get("status", "failed"), m.get("result"), m.get("error"))
                    await self._pump(device_id)
        finally:
            if self.tunnels.get(device_id) is t:
                self.tunnels.pop(device_id, None)
                await self._dev(device_id, state="offline", last_seen_at="now()")

    async def _dev(self, device_id: str, state: str, last_seen_at: str) -> None:
        async with self.pool.acquire() as c:
            await c.execute("UPDATE user_devices SET state=$2, last_seen_at=now() WHERE id=$1::uuid", device_id, state)

    # ---------- jobs ----------
    async def submit(self, user_id: str, device_id: str, kind: str, params: dict,
                     conversation_id: str | None = None) -> str:
        if device_id not in self.tunnels:
            raise ConnectionError("that computer is offline (asleep, closed, or without internet)")
        jid = str(uuid.uuid4())
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO device_jobs (id, user_id, device_id, conversation_id, kind, params)
                VALUES ($1::uuid,$2,$3::uuid,$4,$5,$6)""", jid, user_id, device_id, conversation_id, kind,
                            json.dumps(params))
        self.waiters[jid] = asyncio.Event()
        await self._pump(device_id)
        return jid

    async def wait(self, jid: str, timeout: float) -> dict | None:
        ev = self.waiters.get(jid)
        if ev:
            try:
                await asyncio.wait_for(ev.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        async with self.pool.acquire() as c:
            j = await c.fetchrow("SELECT id::text, kind, status, error, result, steps FROM device_jobs "
                                 "WHERE id=$1::uuid", jid)
        if not j:
            return None
        d = dict(j)
        d["result"] = json.loads(d["result"]) if isinstance(d["result"], str) else d["result"]
        d["steps"] = json.loads(d["steps"]) if isinstance(d["steps"], str) else d["steps"]
        return d

    async def _pump(self, device_id: str) -> None:
        t = self.tunnels.get(device_id)
        if not t:
            return
        async with self.pool.acquire() as c:
            async with c.transaction():
                running = await c.fetchval("SELECT count(*) FROM device_jobs WHERE device_id=$1::uuid "
                                           "AND status='running'", device_id)
                rows = await c.fetch("""SELECT id::text, kind, params FROM device_jobs WHERE device_id=$1::uuid
                    AND status='queued' ORDER BY created_at LIMIT $2 FOR UPDATE SKIP LOCKED""", device_id,
                                     max(0, 1 - running))  # one job at a time: there is one screen and one mouse
                for r in rows:
                    await c.execute("UPDATE device_jobs SET status='running', started_at=now() WHERE id=$1::uuid",
                                    r["id"])
        for r in rows:
            await t.send({"type": "task", "job_id": r["id"], "kind": r["kind"], "params": json.loads(r["params"])})

    async def _finish(self, jid: str, status: str, result, error=None) -> None:
        async with self.pool.acquire() as c:
            j = await c.fetchrow("""UPDATE device_jobs SET status=$2, result=$3, error=$4, finished_at=now()
                WHERE id=$1::uuid RETURNING user_id, conversation_id, kind, params, device_id::text""",
                                 jid, status, json.dumps(result) if result is not None else None, error)
        ev = self.waiters.pop(jid, None)
        if ev:
            ev.set()
        if j and self.activity:
            try:
                async with self.pool.acquire() as c:
                    await c.execute("""INSERT INTO activity_log (user_id, tool, args_summary, result_summary, status)
                        VALUES ($1,$2,$3,$4,$5)""", j["user_id"], f"device__{j['kind']}",
                                    json.dumps(json.loads(j["params"]), ensure_ascii=False)[:200],
                                    (error or str(result or ""))[:300], "ok" if status in ("done", "ok") else status)
            except Exception as e:
                log.debug("activity_log unavailable: %s", e)

    # ---------- approvals: the machine asks, the phone answers ----------
    async def _ask_user(self, t: DeviceTunnel, m: dict) -> None:
        aid = str(m.get("approval_id") or uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._approvals[aid] = {"user_id": t.user_id, "device_id": t.device_id, "fut": fut,
                                "action": str(m.get("action") or "")[:80], "summary": str(m.get("summary") or "")[:400],
                                "risk": str(m.get("risk") or "high")[:20], "t": time.time()}
        if self.on_approval:
            try:
                await self.on_approval(t.user_id, aid, self._approvals[aid])  # push to the phone
            except Exception:
                log.exception("approval push failed")
        try:
            allow = await asyncio.wait_for(fut, APPROVAL_TTL_S)
        except asyncio.TimeoutError:
            allow = False
        finally:
            self._approvals.pop(aid, None)
        await t.send({"type": "approval_result", "approval_id": aid, "allow": bool(allow)})

    def pending_approvals(self, user_id: str) -> list[dict]:
        return [{"id": k, "device_id": v["device_id"], "action": v["action"], "summary": v["summary"],
                 "risk": v["risk"]} for k, v in self._approvals.items() if v["user_id"] == user_id]

    async def answer_approval(self, user_id: str, approval_id: str, allow: bool) -> bool:
        a = self._approvals.get(approval_id)
        if not a or a["user_id"] != user_id or a["fut"].done():
            return False
        a["fut"].set_result(bool(allow))
        return True

    async def cancel_all(self, device_id: str) -> None:
        """Kill switch from the phone: stop the running job on the machine and fail everything queued."""
        t = self.tunnels.get(device_id)
        if t:
            await t.send({"type": "cancel_all"})
        async with self.pool.acquire() as c:
            ids = await c.fetch("UPDATE device_jobs SET status='cancelled', finished_at=now() WHERE device_id=$1::uuid "
                                "AND status IN ('queued','running') RETURNING id::text", device_id)
        for r in ids:
            ev = self.waiters.pop(r["id"], None)
            if ev:
                ev.set()


def _brief(devices: list[dict]) -> list[dict]:
    return [{"id": d["id"], "name": d["name"], "platform": d["platform"], "online": d["online"]} for d in devices]
