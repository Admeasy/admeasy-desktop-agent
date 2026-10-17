"""LLM-facing tools for the user's own computer. The model picks the tool and the `device`; nothing routes on text."""
from __future__ import annotations

import json

from app.devices.cua import ComputerUse

READY = ("[ready, call directly] ")


def _fn(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    props = {"device": {"type": "string", "description": "Computer name or id. Omit when the account has one computer."}}
    props.update(properties or {})
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props, "required": required or []}}}


DEVICE_TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "device_list",
        "description": "List the user's own computers (Mac, Windows) linked to this account: name, platform, online or "
                       "offline, and which OS permissions the desktop app has (screen, accessibility, files). Call it "
                       "first when the user says 'my computer', 'my MacBook', 'my laptop' or 'my PC'.",
        "parameters": {"type": "object", "properties": {}}}},
    _fn("device_use_computer",
        "Do a task on the user's REAL computer by looking at its screen and using mouse and keyboard, as a person would: "
        "open any app (Chrome, Slack, Cursor, VS Code, Terminal, Claude, WhatsApp, Finder), click, type, scroll, switch "
        "windows. Runs a screenshot, decide, act loop. Describe the goal in plain words. Returns the final answer and "
        "what was done. Prefer device_browser for pure web pages and device_shell for plain commands.",
        {"goal": {"type": "string"}, "max_steps": {"type": "integer", "minimum": 1, "maximum": 40}}, ["goal"]),
    _fn("device_screenshot", "Take a screenshot of the user's computer screen now.", {}),
    _fn("device_open",
        "Open an app by name, a file or folder by path, or a URL in the user's default browser on their computer.",
        {"target": {"type": "string", "description": "App name (Slack), path (~/Downloads) or URL."}}, ["target"]),
    _fn("device_browser",
        "Drive the user's own Chrome (their real profile: logged-in sessions, cookies, extensions) with Playwright. "
        "ops: open, navigate, click, type, press, scroll, read, screenshot, search. Cheaper and more reliable than "
        "pixel clicking for web pages. Returns the page title, url, visible text and a screenshot.",
        {"op": {"type": "string", "enum": ["open", "navigate", "click", "type", "press", "scroll", "read",
                                           "screenshot", "search"]},
         "url": {"type": "string"}, "selector": {"type": "string"}, "text": {"type": "string"},
         "key": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}, "dy": {"type": "number"},
         "direction": {"type": "string", "enum": ["back", "forward"]}, "query": {"type": "string"}}, ["op"]),
    _fn("device_shell",
        "Run a shell command on the user's computer (zsh/bash on Mac, PowerShell on Windows): git, npm, python, claude, "
        "cursor, code, open. The user is asked to approve risky commands. Returns exit code and output.",
        {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout_s": {"type": "integer"}}, ["command"]),
    _fn("device_files",
        "List, read, write, mkdir or delete files inside the folders the user shared with Admeasy (Downloads, Desktop, "
        "Documents by default). ops: list, read, write, mkdir, delete.",
        {"op": {"type": "string", "enum": ["list", "read", "write", "mkdir", "delete"]},
         "path": {"type": "string"}, "text": {"type": "string"}}, ["op"]),
    _fn("device_clipboard", "Read or set the clipboard text on the user's computer.",
        {"op": {"type": "string", "enum": ["get", "set"]}, "text": {"type": "string"}}, ["op"]),
    _fn("device_cancel", "Stop whatever is running on the user's computer right now and clear the queue.", {}),
]
DEVICE_TOOL_NAMES = {t["function"]["name"] for t in DEVICE_TOOL_SCHEMAS}
_KIND = {"device_screenshot": "screenshot", "device_open": "open", "device_browser": "browser",
         "device_shell": "shell", "device_files": "files", "device_clipboard": "clipboard"}


def _strip(res: dict | None) -> dict:
    """Screenshots are heavy: keep the bytes for the vision loop and the phone, not for the chat model."""
    out = dict(res or {})
    if out.get("screenshot_b64"):
        out["screenshot_attached"] = True
        out.pop("screenshot_b64")
    return out


class DeviceTools:
    def __init__(self, svc, cua: ComputerUse | None = None, on_screenshot=None):
        self.svc = svc
        self.cua = cua or ComputerUse(svc)
        self.on_screenshot = on_screenshot  # async (user_id, b64) -> None, shows the frame in the app

    async def call(self, user_id: str, name: str, args: dict, conversation_id: str | None = None) -> str:
        try:
            out = await self._call(user_id, name, args or {}, conversation_id)
        except ConnectionError as e:
            out = {"status": "offline", "error": str(e)}
        except Exception as e:
            out = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        return json.dumps(out, ensure_ascii=False, default=str)

    async def _call(self, user_id: str, name: str, args: dict, conv: str | None) -> dict:
        if name == "device_list":
            return {"devices": await self.svc.list(user_id)}
        dev = await self.svc.pick(user_id, args.get("device"))
        if dev.get("error"):
            return dev
        did = dev["id"]
        if name == "device_cancel":
            await self.svc.cancel_all(did)
            return {"status": "done", "device": dev["name"]}
        if name == "device_use_computer":
            r = await self.cua.run(user_id, did, str(args.get("goal") or ""), conv,
                                   int(args.get("max_steps") or 15), on_frame=self.on_screenshot)
            return {**r, "device": dev["name"]}
        kind = _KIND.get(name)
        if not kind:
            return {"status": "failed", "error": f"unknown tool {name}"}
        params = {k: v for k, v in args.items() if k != "device"}
        jid = await self.svc.submit(user_id, did, kind, params, conv)
        j = await self.svc.wait(jid, float(params.get("timeout_s") or 120) + 30)
        if not j:
            return {"status": "failed", "error": "no answer from the computer", "device": dev["name"]}
        res = j.get("result") or {}
        if res.get("screenshot_b64") and self.on_screenshot:
            await self.on_screenshot(user_id, res["screenshot_b64"])
        return {"status": j["status"], "error": j.get("error"), "result": _strip(res), "device": dev["name"]}
