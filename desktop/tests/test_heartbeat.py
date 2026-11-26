import asyncio

import pytest

from admeasy_desktop.heartbeats import run_with_heartbeat


@pytest.mark.asyncio
async def test_heartbeat_emits_during_long_call():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def slow():
        await asyncio.sleep(0.35)
        return {"status": "ok"}

    out = await run_with_heartbeat("j-hb", send, slow(), interval_s=0.08)
    assert out["status"] == "ok"
    heartbeats = [m for m in sent if m.get("type") == "heartbeat"]
    assert heartbeats
    assert heartbeats[0]["job_id"] == "j-hb"