"""Chat window, scoped folders, pairing links, reminders, and the shell session."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from admeasy_desktop import auth, config
from admeasy_desktop.chat_bridge import present_messages
from admeasy_desktop.config import Settings
from admeasy_desktop.folders import grant, reject_reason
from admeasy_desktop.fragments import fragment_reply
from admeasy_desktop.links import create_job, parse_run_url
from admeasy_desktop.policy import judge
from admeasy_desktop.reminders import add_reminder, deliver_due
from admeasy_desktop.safety import folder_roots, gate_job
from admeasy_desktop.ui.server import UiState, serve


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(auth, "_kr", lambda: None)


def test_fragments_are_short_bubbles():
    parts = fragment_reply("Hello there. This is the next thought. And one more.")
    assert len(parts) >= 2
    assert all(len(p) <= 180 for p in parts)
    assert fragment_reply("   ") == []


def test_history_rows_split_assistant_text():
    rows = present_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "text": "Sure. I opened the page."},
    ])
    assert rows[0]["role"] == "user"
    assert sum(1 for row in rows if row["role"] == "assistant") >= 2


def test_blocklist_beats_allowlist_and_trusted_mode():
    denied = judge("shell", {"command": "echo hi"}, "trusted", [], allowlist=["echo hi"], blocklist=["echo hi"])
    assert not denied.allow
    allowed = judge("shell", {"command": "echo hi"}, "ask_always", [], allowlist=["echo hi"])
    assert allowed.allow and not allowed.ask


def test_autonomous_jobs_skip_prompts_by_denying_them():
    risky = judge("shell", {"command": "rm notes.txt"}, "autopilot", ["/tmp"], autonomous=True)
    assert not risky.allow
    quiet = judge("shell", {"command": "pwd"}, "autopilot", ["/tmp"], autonomous=True)
    assert quiet.allow and not quiet.ask


def test_new_install_does_not_act_until_onboarding():
    waiting = Settings(gate_until_onboarding=True, onboarding_complete=False)
    assert gate_job(waiting, "shell", {})["status"] == "permission_missing"
    assert gate_job(waiting, "status", {}) is None
    off = Settings(capability_toggles={"shell": False, "files": True, "screen": True, "input": True, "browser": True, "notify": True})
    assert gate_job(off, "browser", {}) is None
    assert gate_job(off, "shell", {"command": "pwd"})["result"]["capability"] == "shell"


def test_folder_grant_rejects_the_whole_disk(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    assert reject_reason("/")
    settings = Settings(use_approved_folders_only=True, approved_folders=[], shared_folders=[])
    project = tmp_path / "proj"
    project.mkdir()
    saved = grant(settings, str(project))
    assert Path(saved) == project.resolve()
    assert folder_roots(settings) == [str(project.resolve())]
    with pytest.raises(ValueError):
        grant(settings, str(Path.home()))


def test_run_link_rejects_raw_commands(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    assert parse_run_url("admeasy://run?job=abc123def456") == "abc123def456"
    with pytest.raises(ValueError):
        parse_run_url("admeasy://run?job=abc123def456&command=rm%20-rf%20/")
    job = create_job("pwd", ["/tmp"])
    assert job["url"].startswith("admeasy://run?job=")
    with pytest.raises(ValueError):
        create_job("rm -rf /", ["/tmp"], mode="trusted")


def test_due_reminder_is_delivered_once(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    add_reminder(Settings(backend="http://127.0.0.1:9"), "stand up", "2000-01-01T00:00:00+00:00")
    first = deliver_due(now=datetime(2000, 1, 1, 0, 1, tzinfo=timezone.utc), notify=False)
    assert first and first[0]["text"] == "stand up"
    assert deliver_due(now=datetime(2000, 1, 1, 0, 2, tzinfo=timezone.utc), notify=False) == []


def test_window_serves_theme_installer_and_folder_gate(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    state = UiState(Settings(backend="http://127.0.0.1:9", gate_until_onboarding=True, onboarding_complete=False))
    srv, port = serve(state)
    try:
        base = f"http://127.0.0.1:{port}"
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "https://admeasy.ai" in page
        assert "__TOKEN__" not in page
        css = urllib.request.urlopen(base + "/theme.css").read().decode()
        assert "--pink: #e278a0" in css
        assert "--bp-md: 720px" in css
        tokens = json.load(open(Path(__file__).resolve().parents[1] / "admeasy_desktop/ui/brand-tokens.json"))
        assert tokens["colors"]["bg"] == "#f6f3ee"
        script = urllib.request.urlopen(base + "/install.sh").read().decode()
        assert "bash -s --" in script or "--pair" in script
        snap = json.load(urllib.request.urlopen(base + "/api/state"))
        assert snap["needs_invite"] or "perms_ready" in snap
        project = tmp_path / "notes"
        project.mkdir()

        def post(path, payload):
            req = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as res:
                return json.load(res)

        post("/api/folders", {"path": str(project)})
        listed = json.load(urllib.request.urlopen(base + "/api/state"))
        assert str(project.resolve()) in listed["folders"]
        try:
            post("/api/folders", {"path": "/"})
            raise AssertionError("root folder was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        srv.shutdown()


@pytest.mark.asyncio
async def test_pty_session_keeps_the_working_directory():
    if sys.platform == "win32":
        pytest.skip("POSIX pty")
    from admeasy_desktop.executors import terminal_exec
    spawned = await terminal_exec.run({"op": "spawn", "cwd": "/tmp"})
    sid = spawned["result"]["session_id"]
    try:
        assert spawned["result"]["pty"] is True
        got = await terminal_exec.run({
            "op": "write", "session_id": sid, "data": "cd /tmp && pwd\n", "settle_s": 0.8,
        })
        assert "/tmp" in got["result"]["output"]
    finally:
        await terminal_exec.run({"op": "close", "session_id": sid})


@pytest.mark.asyncio
async def test_chat_socket_streams_fragmented_bubbles():
    import asyncio
    import websockets
    from admeasy_desktop.chat_bridge import ChatBridge

    async def handler(ws):
        incoming = json.loads(await ws.recv())
        assert incoming["type"] == "text" and incoming["text"] == "hi"
        await ws.send(json.dumps({"type": "session", "conversation_id": "c1"}))
        await ws.send(json.dumps({"type": "token", "text": "Hello. "}))
        await ws.send(json.dumps({"type": "done", "text": "Hello. This is the next sentence."}))
        await asyncio.sleep(0.3)

    async with websockets.serve(handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        bridge = ChatBridge(Settings(backend=f"http://127.0.0.1:{port}"))
        bridge._token = lambda: "token"
        bridge.send("hi")
        seen = []
        for _ in range(40):
            seen.extend(bridge.drain())
            finals = [row for row in seen if row.get("type") == "final"]
            if finals:
                assert len(finals[0]["bubbles"]) >= 2
                assert bridge.conversation_id == "c1"
                return
            await asyncio.sleep(0.05)
    raise AssertionError(bridge.error or seen)
