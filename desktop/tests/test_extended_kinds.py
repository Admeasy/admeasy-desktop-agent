"""Dispatch coverage for expanded job kinds (executors stubbed)."""
from __future__ import annotations

import pytest

from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings
from admeasy_desktop.job_kinds import JOB_KINDS


@pytest.fixture
def agent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "admeasy_desktop.executors.screen.screenshot",
        lambda: {"screenshot_b64": "AA==", "size": [100, 100]},
    )
    class _B:
        async def run(self, p):
            return {"status": "done", "result": {"url": "https://example.com", "title": "t", "text": "hi"}}

    monkeypatch.setattr("admeasy_desktop.agent.Browser", lambda: _B())
    async def _shell(p, cancel=None):
        return {"status": "done", "result": {"exit_code": 0, "output": "ok"}}

    monkeypatch.setattr("admeasy_desktop.executors.system.shell", _shell)
    monkeypatch.setattr(
        "admeasy_desktop.executors.system.files",
        lambda p, roots: {"status": "done", "result": {"path": p.get("path"), "items": []}},
    )
    monkeypatch.setattr(
        "admeasy_desktop.executors.system.clipboard",
        lambda p: {"status": "done", "result": {"text": ""}},
    )
    monkeypatch.setattr(
        "admeasy_desktop.executors.system.open_target",
        lambda p: {"status": "done", "result": {"opened": p.get("target")}},
    )
    async def _term(p, on_output=None):
        return {"status": "done", "result": {"sessions": []}}

    async def _cli(p, on_output=None):
        return {"status": "done", "result": {"profiles": ["git"]}}

    async def _app(p, on_output=None):
        return {"status": "done", "result": {"opened": "x"}}

    monkeypatch.setattr("admeasy_desktop.executors.terminal_exec.run", _term)
    monkeypatch.setattr("admeasy_desktop.executors.cli_exec.run", _cli)
    monkeypatch.setattr("admeasy_desktop.executors.app_exec.run", _app)
    monkeypatch.setattr("admeasy_desktop.executors.ide_exec.run", lambda p: {"status": "done", "result": {"opened": "."}})
    async def _wa(p):
        return {"status": "done", "result": {"url": "https://web.whatsapp.com/"}}

    monkeypatch.setattr("admeasy_desktop.executors.whatsapp_exec.run", _wa)
    monkeypatch.setattr("admeasy_desktop.executors.messages_exec.run", lambda p: {"status": "done", "result": {"messages": []}})
    monkeypatch.setattr("admeasy_desktop.executors.comms_exec.run", lambda p: {"status": "done", "result": {"notifications": []}})
    monkeypatch.setattr("admeasy_desktop.executors.mail_exec.run", lambda p: {"status": "done", "result": {"unread_inbox": 0}})
    return Agent(Settings())


@pytest.mark.asyncio
async def test_dispatch_all_kinds(agent, tmp_path):
    samples = {
        "screenshot": {},
        "open": {"target": "https://example.com"},
        "browser": {"op": "read", "url": "https://example.com"},
        "shell": {"command": "echo hi"},
        "files": {"op": "list", "path": str(tmp_path)},
        "clipboard": {"op": "get"},
        "cua": {"action": {"type": "done", "answer": "ok"}},
        "terminal": {"op": "list"},
        "cli": {"op": "profiles"},
        "app": {"op": "which", "name": "python"},
        "ide": {"op": "open", "path": "."},
        "whatsapp": {"op": "status"},
        "messages": {"op": "recent", "limit": 1},
        "comms": {"op": "notifications", "limit": 1},
        "mail": {"op": "unread"},
    }
    assert set(samples) == JOB_KINDS
    for kind, params in samples.items():
        out = await agent.dispatch(f"j-{kind}", kind, params)
        assert out.get("status") in ("done", "failed", "needs_login", "needs_human", "needs_permission")


def test_job_kind_count():
    assert len(JOB_KINDS) == 15
