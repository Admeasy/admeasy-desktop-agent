"""Each backend job kind runs twice in one tunnel session (plus cancel_all)."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest
import websockets

from admeasy_desktop import agent as agent_mod
from admeasy_desktop.config import Settings
from admeasy_desktop.job_kinds import JOB_KINDS

# Full tunnel session harness (heavy); extended kinds covered in test_extended_kinds.py
SESSION_KINDS = frozenset({"screenshot", "open", "browser", "shell", "files", "clipboard", "cua"})


async def _session(monkeypatch, tmp_path, task_specs: list[dict], *, approval_mode: str = "trusted") -> list[dict]:
    """Run tasks sequentially on one stub backend; return result messages in order."""
    results: list[dict] = []
    done = asyncio.Event()

    async def backend(ws):
        await ws.recv()  # hello
        for spec in task_specs:
            await ws.send(json.dumps({"type": "task", **spec}))
        while len(results) < len(task_specs):
            m = json.loads(await ws.recv())
            if m.get("type") == "approval_request":
                await ws.send(json.dumps({"type": "approval_result", "approval_id": m["approval_id"], "allow": True}))
                continue
            if m.get("type") == "result":
                results.append(m)
        done.set()

    async with websockets.serve(backend, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        monkeypatch.setattr(agent_mod, "load_secret", lambda k: {"device_id": "d", "device_token": "t"}.get(k))
        s = Settings(backend=f"http://127.0.0.1:{port}", shared_folders=[str(tmp_path)], approval_mode=approval_mode)
        agent = agent_mod.Agent(s)
        tunnel = asyncio.create_task(agent.tunnel())
        await asyncio.wait_for(done.wait(), 30)
        tunnel.cancel()
        try:
            await asyncio.wait_for(tunnel, timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    return results


def _task(jid: str, kind: str, params: dict) -> dict:
    return {"job_id": jid, "kind": kind, "params": params}


class _FakePg:
    def size(self):
        return (1920, 1080)


def _on_ci() -> bool:
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


@pytest.fixture(autouse=True)
def _ci_grant_screen_permissions(monkeypatch):
    """GitHub macOS runners lack Screen Recording / Accessibility; keep production checks unchanged."""
    if not _on_ci():
        return
    granted = {"screen": True, "accessibility": True}
    monkeypatch.setattr(agent_mod.permissions, "wire_snapshot", lambda: dict(granted))
    monkeypatch.setattr(agent_mod.permissions, "missing", lambda snap: [])
    monkeypatch.setattr(agent_mod.permissions, "missing_for_kind", lambda kind, params, snap: [])


@pytest.fixture(autouse=True)
def _stub_executors(monkeypatch):
    monkeypatch.setattr(agent_mod.screen, "_pg", lambda: _FakePg())
    monkeypatch.setattr(agent_mod.screen, "screenshot", lambda: {"screenshot_b64": "AA==", "size": [640, 480]})
    monkeypatch.setattr(agent_mod.screen, "act", lambda *a, **k: None)

    async def _browser_run(self, p: dict) -> dict:
        return {"status": "done", "result": {"url": p.get("url", "https://example.com"), "title": "ok", "text": "hi"}}

    monkeypatch.setattr(agent_mod.Browser, "run", _browser_run)
    monkeypatch.setattr(agent_mod.system, "open_target", lambda p: {"status": "done", "result": {"opened": p.get("target")}})

    import pyperclip

    store = {"text": ""}

    def _copy(t):
        store["text"] = t

    def _paste():
        return store["text"]

    monkeypatch.setattr(pyperclip, "copy", _copy)
    monkeypatch.setattr(pyperclip, "paste", _paste)


@pytest.mark.parametrize("kind", sorted(SESSION_KINDS))
@pytest.mark.asyncio
async def test_job_kind_twice_in_one_session(kind, monkeypatch, tmp_path):
    params: dict[str, Any]
    if kind == "screenshot":
        params = {}
    elif kind == "open":
        params = {"target": "https://example.com"}
    elif kind == "browser":
        params = {"op": "read", "url": "https://example.com"}
    elif kind == "shell":
        params = {"command": "echo ok"}
    elif kind == "files":
        f = tmp_path / "a.txt"
        params = {"op": "write", "path": str(f), "text": "data"}
    elif kind == "clipboard":
        params = {"op": "set", "text": "clip"}
    elif kind == "cua":
        params = {"action": {"type": "screenshot"}}
    else:
        pytest.fail(f"unhandled kind {kind}")

    specs = [_task(f"{kind}-1", kind, params), _task(f"{kind}-2", kind, params)]
    if kind == "files":
        specs[1] = _task("files-2", "files", {"op": "read", "path": str(tmp_path / "a.txt")})
    if kind == "clipboard":
        specs[1] = _task("clipboard-2", "clipboard", {"op": "get"})

    results = await _session(monkeypatch, tmp_path, specs)
    assert len(results) == 2
    assert results[0]["job_id"].startswith(kind) or kind in results[0]["job_id"]
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "ok"
    if kind == "clipboard":
        assert results[1]["result"]["text"] == "clip"
    if kind == "files":
        import base64
        assert base64.b64decode(results[1]["result"]["content_b64"]).decode() == "data"


def test_session_kinds_subset_of_job_kinds():
    assert SESSION_KINDS <= JOB_KINDS


@pytest.mark.asyncio
async def test_cancel_all_cancels_queued_job(monkeypatch, tmp_path):
    got: list[dict] = []
    proceed = asyncio.Event()

    async def backend(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "task", "job_id": "slow", "kind": "shell",
                                  "params": {"command": "sleep 3 && echo slow"}}))
        await ws.send(json.dumps({"type": "task", "job_id": "queued", "kind": "shell",
                                  "params": {"command": "echo q"}}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"type": "cancel_all"}))
        proceed.set()
        while len(got) < 2:
            m = json.loads(await ws.recv())
            if m.get("type") == "result":
                got.append(m)

    async with websockets.serve(backend, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        monkeypatch.setattr(agent_mod, "load_secret", lambda k: {"device_id": "d", "device_token": "t"}.get(k))
        s = Settings(backend=f"http://127.0.0.1:{port}", shared_folders=[str(tmp_path)], approval_mode="trusted")
        agent = agent_mod.Agent(s)
        tunnel = asyncio.create_task(agent.tunnel())
        await asyncio.wait_for(proceed.wait(), 10)
        await asyncio.sleep(2)
        tunnel.cancel()
    statuses = {m["job_id"]: m["status"] for m in got}
    assert statuses.get("queued") == "cancelled"
    assert statuses.get("slow") in ("cancelled", "ok", "error", "blocked")
