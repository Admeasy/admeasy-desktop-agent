import asyncio

import pytest

from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings
from admeasy_desktop.policy import Verdict


@pytest.mark.asyncio
async def test_approval_parks_without_timeout(monkeypatch):
    sent = []
    a = Agent(Settings(approval_mode="ask_risky"))
    async def _send(m):
        sent.append(m)

    a.send = _send
    monkeypatch.setattr("admeasy_desktop.notify.toast", lambda *args: True)

    async def answer_later():
        await asyncio.sleep(0.2)
        for aid, fut in list(a.approvals.items()):
            if not fut.done():
                fut.set_result(True)

    asyncio.create_task(answer_later())
    v = Verdict(True, ask=True, reason="run: echo hi", risk="high")
    allowed = await a.ask_user("jid", "shell", v)
    assert allowed is True
    types = [m["type"] for m in sent]
    assert "approval_request" in types
    assert "needs_approval" in types
    parked = sent[next(i for i, m in enumerate(sent) if m["type"] == "needs_approval")]
    assert parked["job_id"] == "jid"
    assert parked["status"] == "needs_approval"
    assert parked.get("pending_action", {}).get("action") == "shell"


@pytest.mark.asyncio
async def test_scheduled_job_can_request_approval():
    from admeasy_desktop.policy import judge

    v = judge("shell", {"command": "rm foo"}, "autopilot", ["/tmp"], autonomous=True)
    assert v.ask is True
    assert v.allow is True