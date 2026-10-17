"""End to end over a real WebSocket: backend-side stub sends tasks, the real Agent runs them and asks for approval."""
import asyncio
import json

import pytest
import websockets

from admeasy_desktop import agent as agent_mod
from admeasy_desktop.config import Settings


@pytest.mark.asyncio
async def test_task_approval_result_roundtrip(monkeypatch, tmp_path):
    got = {}
    done = asyncio.Event()

    async def backend(ws):
        hello = json.loads(await ws.recv())
        got["hello"] = hello
        await ws.send(json.dumps({"type": "task", "job_id": "j1", "kind": "shell", "params": {"command": "echo hi"}}))
        while True:  # the agent also sends a `permissions` report right after hello
            req = json.loads(await ws.recv())
            if req["type"] == "approval_request":  # shell asks the user first
                break
        got["approval"] = req
        await ws.send(json.dumps({"type": "approval_result", "approval_id": req["approval_id"], "allow": True}))
        while True:
            m = json.loads(await ws.recv())
            if m["type"] == "result":
                got["result"] = m
                break
        await ws.send(json.dumps({"type": "task", "job_id": "j2", "kind": "shell", "params": {"command": "rm -rf /"}}))
        while True:
            m = json.loads(await ws.recv())
            if m["type"] == "result":
                got["blocked"] = m
                break
        await ws.send(json.dumps({"type": "task", "job_id": "j3", "kind": "files",
                                  "params": {"op": "read", "path": "/etc/passwd"}}))
        while True:
            m = json.loads(await ws.recv())
            if m["type"] == "result":
                got["outside"] = m
                break
        done.set()

    async with websockets.serve(backend, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        monkeypatch.setattr(agent_mod, "load_secret", lambda k: {"device_id": "d", "device_token": "t"}.get(k))
        s = Settings(backend=f"http://127.0.0.1:{port}", shared_folders=[str(tmp_path)])
        # the real backend path is /devices/tunnel; the stub accepts any path
        a = agent_mod.Agent(s)
        t = asyncio.create_task(a.tunnel())
        await asyncio.wait_for(done.wait(), 15)
        a.cancel_all()
        t.cancel()
        try:
            await asyncio.wait_for(t, timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    assert got["hello"]["type"] == "hello" and got["hello"]["capabilities"]["mouse_keyboard"]
    assert got["approval"]["action"] == "shell" and "echo hi" in got["approval"]["summary"]
    assert got["result"]["status"] == "ok" and "hi" in got["result"]["result"]["output"]
    assert got["blocked"]["status"] == "blocked"
    assert got["outside"]["status"] == "blocked"
