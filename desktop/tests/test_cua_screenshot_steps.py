import asyncio
from unittest.mock import MagicMock

import pytest

from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings


@pytest.mark.asyncio
async def test_cua_screenshot_after_click_action(monkeypatch):
    s = Settings(shared_folders=["/tmp"])
    a = Agent(s)
    steps = []

    async def capture_step(jid, text, objective_id=None):
        steps.append(text)

    monkeypatch.setattr(a, "step", capture_step)
    monkeypatch.setattr(
        "admeasy_desktop.executors.screen.act",
        lambda action, scaler=None: None,
    )
    monkeypatch.setattr(
        "admeasy_desktop.executors.screen.settle_seconds",
        lambda action: 0.01,
    )
    monkeypatch.setattr("admeasy_desktop.ui_settle.wait_for_settle", lambda *a, **k: 0.0)
    monkeypatch.setattr(
        "admeasy_desktop.executors.screen.screenshot",
        lambda: {"screenshot_b64": "AA==", "size": [1280, 800], "elements": [{"id": 1}]},
    )
    monkeypatch.setattr(
        "admeasy_desktop.executors.screen._pg",
        lambda: MagicMock(size=lambda: (1440, 900)),
    )
    monkeypatch.setattr("admeasy_desktop.executors.screen.Scaler", lambda a, b: MagicMock())

    out = await a.dispatch("j1", "cua", {"action": {"type": "click", "element_id": 3}})
    assert out["status"] == "ok"
    assert any("click element_id=3" in t for t in steps)
    assert any(t.startswith("screenshot ") for t in steps)
