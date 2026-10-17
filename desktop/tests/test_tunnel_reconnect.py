"""Reconnect buffer + idempotency (no live network)."""
import json

import pytest

from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings
from admeasy_desktop.job_store import JobStore


@pytest.mark.asyncio
async def test_hello_replays_pending_results(tmp_path):
    s = Settings(backend="http://127.0.0.1:9", shared_folders=[str(tmp_path)])
    a = Agent(s)
    a.store = JobStore(tmp_path / "store.json")
    a.store.buffer_result({"type": "result", "job_id": "j-buffer", "status": "ok", "result": {"resumed": True}})
    sent = []

    class _Ws:
        async def send(self, raw: str) -> None:
            sent.append(json.loads(raw))

    a.ws = _Ws()
    await a.hello()
    assert any(m.get("job_id") == "j-buffer" for m in sent)


@pytest.mark.asyncio
async def test_idempotency_key_skips_second_dispatch(tmp_path):
    s = Settings(backend="http://127.0.0.1:9", shared_folders=[str(tmp_path)])
    a = Agent(s)
    a.store = JobStore(tmp_path / "store.json")
    out = []

    async def capture(msg):
        out.append(msg)

    a.send = capture
    job = {"job_id": "j1", "kind": "status", "params": {"idempotency_key": "idem", "domains": []}}
    await a.run_job(job)
    await a.run_job({**job, "job_id": "j2"})
    assert len(out) == 2
    assert out[0]["result"] == out[1]["result"]
    assert out[0]["status"] == "ok"
