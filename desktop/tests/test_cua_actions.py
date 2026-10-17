import asyncio

import pytest

from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings


@pytest.mark.asyncio
async def test_cua_done_and_needs_login(monkeypatch):
    s = Settings(shared_folders=["/tmp"])
    a = Agent(s)
    done = await a.dispatch("j1", "cua", {"action": {"type": "done", "answer": "finished"}})
    assert done["status"] == "done" and done["result"]["answer"] == "finished"
    login = await a.dispatch("j2", "cua", {"action": {"type": "needs_login"}})
    assert login["status"] == "needs_login"
