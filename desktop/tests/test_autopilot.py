import asyncio
import json

from admeasy_desktop import config as cfg
from admeasy_desktop.executors.browser import page_typed_ok, typed_check
from admeasy_desktop.policy import judge

R = ["/tmp"]


def ask(kind, p):
    v = judge(kind, p, "autopilot", R)
    return v.allow, v.ask


def test_ui_actions_never_ask():
    for kind, p in [("open", {"target": "Claude"}), ("browser", {"op": "type", "text": "send this prompt"}),
                    ("browser", {"op": "click"}), ("cua", {"action": {"type": "click", "x": 1, "y": 2}}),
                    ("cua", {"action": {"type": "type", "text": "submit the form"}}),
                    ("cua", {"action": {"type": "key", "key": "cmd+w"}}), ("clipboard", {"op": "set"}),
                    ("app", {"op": "open", "name": "Claude"}), ("whatsapp", {"op": "type", "text": "hi"}),
                    ("mail", {"op": "compose"}), ("ide", {"op": "command"}), ("shell", {"command": "ls ~"}),
                    ("files", {"op": "write", "path": "/tmp/a.txt"})]:
        assert ask(kind, p) == (True, False), (kind, p)


def test_only_destructive_or_final_sends_ask():
    for kind, p in [("shell", {"command": "rm -r /tmp/x"}), ("files", {"op": "delete", "path": "/tmp/a"}),
                    ("cua", {"action": {"type": "key", "key": "cmd+delete"}}),
                    ("app", {"op": "install", "name": "x"}), ("messages", {"op": "send", "to": "x"}),
                    ("comms", {"op": "continuity_call", "number": "1"}), ("whatsapp", {"op": "send"})]:
        assert ask(kind, p) == (True, True), (kind, p)
    assert judge("shell", {"command": "rm -rf ~"}, "autopilot", R).allow is False
    assert judge("files", {"op": "list", "path": "/etc"}, "autopilot", R).allow is False


def test_autopilot_is_default_and_old_default_migrates(tmp_path, monkeypatch):
    assert cfg.Settings().approval_mode == "autopilot"
    f = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_PATH", f)
    f.write_text(json.dumps({"approval_mode": "ask_risky"}))
    assert cfg.Settings.load().approval_mode == "autopilot"
    f.write_text(json.dumps({"approval_mode": "ask_risky", "approval_mode_chosen": True}))
    assert cfg.Settings.load().approval_mode == "ask_risky"


def test_typed_read_back():
    assert typed_check("dental clinic  website", "Make a dental clinic website") is True
    assert typed_check("hello", "") is False
    assert typed_check("hello", None) is None

    class Page:
        def __init__(self, v):
            self.v = v

        async def evaluate(self, js):
            if isinstance(self.v, Exception):
                raise self.v
            return self.v
    assert asyncio.run(page_typed_ok(Page("hello world"), "hello")) is True
    assert asyncio.run(page_typed_ok(Page(RuntimeError("x")), "hello")) is None
