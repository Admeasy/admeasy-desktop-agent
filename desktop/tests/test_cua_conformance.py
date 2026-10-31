"""Shared contract: each CUA step returns ok + fresh screenshot + elements + last_action."""
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings

FIXTURE = Path(__file__).resolve().parents[2] / "docs/contract-fixtures/instagram_flow.json"


@pytest.mark.asyncio
async def test_instagram_flow_six_distinct_screenshots(monkeypatch):
    data = json.loads(FIXTURE.read_text())
    steps = data["steps"]
    s = Settings(shared_folders=["/tmp"])
    agent = Agent(s)
    hashes: list[str] = []
    n = 0

    def fake_screenshot(som=True):
        nonlocal n
        n += 1
        body = f"shot-{n}".encode()
        h = hashlib.sha256(body).hexdigest()
        hashes.append(h)
        return {
            "screenshot_b64": body.hex(),
            "size": [1280, 800],
            "elements": [{"id": i, "role": "button", "name": f"el{i}"} for i in range(1, 8)],
        }

    monkeypatch.setattr("admeasy_desktop.executors.screen.screenshot", fake_screenshot)
    monkeypatch.setattr("admeasy_desktop.executors.screen.act", lambda action, scaler=None: {
        "type": action.get("type"),
        "input": "test",
        "pointer_ok": True,
        "ax_ok": False,
    })
    monkeypatch.setattr("admeasy_desktop.ui_settle.wait_for_settle", lambda *a, **k: 0.0)
    monkeypatch.setattr("admeasy_desktop.executors.screen._pg", lambda: MagicMock(size=lambda: (1440, 900)))
    monkeypatch.setattr("admeasy_desktop.input_darwin.accessibility_trusted", lambda: True)

    for step in steps:
        out = await agent.dispatch(f"j{len(hashes)}", "cua", {"action": step["action"]})
        assert out["status"] == "ok"
        assert out["result"]["screenshot_b64"]
        assert out["result"]["size"] == [1280, 800]
        assert isinstance(out["result"].get("elements"), list)
        if step["action"].get("type") not in (None, "screenshot"):
            assert "last_action" in out["result"]
            assert out["result"]["last_action"].get("pointer_ok") is True

    assert len(hashes) >= data["expect"]["min_actions_with_screenshot"]
    assert len(set(hashes)) >= data["expect"]["distinct_screenshot_hashes"]


def test_contract_version_handshake():
    caps = Agent(Settings()).capabilities()
    assert caps["contract_version"] == "0.5.0"
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["contract_version"] == caps["contract_version"]
