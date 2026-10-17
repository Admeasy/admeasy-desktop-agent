"""Device tools: schema shape, device selection, action mapping. No database needed."""
import asyncio
import json

from app.devices.cua import job_succeeded, to_action
from app.devices.service import DeviceService
from app.devices.tools import DEVICE_TOOL_NAMES, DEVICE_TOOL_SCHEMAS, DeviceTools


class FakeSvc(DeviceService):
    def __init__(self, devices):
        self._devices = devices
        self.sent = []

    async def list(self, user_id):
        return self._devices

    async def submit(self, user_id, device_id, kind, params, conversation_id=None):
        self.sent.append((device_id, kind, params))
        return "j1"

    async def wait(self, jid, timeout):
        return {"status": "done", "error": None, "result": {"output": "ok", "screenshot_b64": "AAAA"}}


MAC = {"id": "d1", "name": "Ali's MacBook", "platform": "macos", "online": True}
PC = {"id": "d2", "name": "Office PC", "platform": "windows", "online": False}


def test_schemas_are_valid_and_named():
    assert {"device_list", "device_use_computer", "device_browser", "device_shell", "device_files"} <= DEVICE_TOOL_NAMES
    for t in DEVICE_TOOL_SCHEMAS:
        assert t["function"]["parameters"]["type"] == "object"


def test_pick_single_device_needs_no_name():
    r = asyncio.run(FakeSvc([MAC]).pick("u", None))
    assert r["id"] == "d1"


def test_pick_by_partial_name_and_ambiguity():
    s = FakeSvc([MAC, PC])
    assert asyncio.run(s.pick("u", "macbook"))["id"] == "d1"
    assert asyncio.run(s.pick("u", "windows"))["id"] == "d2"
    assert "devices" in asyncio.run(s.pick("u", None)) or asyncio.run(s.pick("u", None))["id"] == "d1"  # one online


def test_no_devices_error_is_actionable():
    r = asyncio.run(FakeSvc([]).pick("u", None))
    assert "desktop app" in r["error"]


def test_tool_call_strips_screenshot_from_chat_model_output():
    frames = []

    async def on_shot(uid, b64):
        frames.append(b64)
    t = DeviceTools(FakeSvc([MAC]), on_screenshot=on_shot)
    out = json.loads(asyncio.run(t.call("u", "device_shell", {"command": "ls"})))
    assert "screenshot_b64" not in json.dumps(out) and frames == ["AAAA"]
    assert out["device"] == "Ali's MacBook"


def test_job_succeeded_accepts_desktop_ok_status():
    assert job_succeeded("ok")
    assert job_succeeded("done")
    assert not job_succeeded("error")


def test_to_action_maps_computer_tool_calls():
    assert to_action({"action": "left_click", "coordinate": [10, 20]}) == {"type": "click", "x": 10.0, "y": 20.0}
    assert to_action({"action": "key", "text": "ctrl+c"})["key"] == "ctrl+c"
    assert to_action({"action": "scroll", "coordinate": [1, 1], "scroll_direction": "up", "scroll_amount": 2})["dy"] == -200
    assert to_action({"action": "nonsense"}) == {"type": "screenshot"}
    assert to_action({"action": "done", "text": "finished"}) == {"type": "done", "answer": "finished"}
