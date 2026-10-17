"""Several tasks in one tunnel session."""
import asyncio
import json

import pytest
import websockets

from admeasy_desktop import agent as agent_mod
from admeasy_desktop.config import Settings


@pytest.mark.asyncio
async def test_three_shell_jobs_in_sequence(monkeypatch, tmp_path):
    results = []
    done = asyncio.Event()

    async def backend(ws):
        await ws.recv()  # hello
        for i in range(3):
            await ws.send(json.dumps({"type": "task", "job_id": f"j{i}", "kind": "shell",
                                      "params": {"command": f"echo job{i}"}}))
            while True:
                m = json.loads(await ws.recv())
                if m["type"] == "result" and m["job_id"] == f"j{i}":
                    results.append(m)
                    break
        done.set()

    async with websockets.serve(backend, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        monkeypatch.setattr(agent_mod, "load_secret", lambda k: {"device_id": "d", "device_token": "t"}.get(k))
        s = Settings(backend=f"http://127.0.0.1:{port}", shared_folders=[str(tmp_path)], approval_mode="trusted")
        a = agent_mod.Agent(s)
        t = asyncio.create_task(a.tunnel())
        await asyncio.wait_for(done.wait(), 15)
        t.cancel()
        try:
            await asyncio.wait_for(t, timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    assert len(results) == 3
    assert all(r["status"] == "ok" for r in results)
    assert "job0" in results[0]["result"]["output"]
