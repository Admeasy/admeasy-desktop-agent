"""Screenshot -> decide -> act loop for a real desktop (Claude computer-use tool on Bedrock, vision model fallback)."""
from __future__ import annotations

import base64
import json
import logging

from app.vm_vision import resolve_vm_vision, vision_complete, vision_ready

log = logging.getLogger(__name__)

# Desktop agent v0.4+ returns job status "ok"; legacy agents used "done".
_JOB_OK = frozenset({"ok", "done"})


def job_succeeded(status: str | None) -> bool:
    return str(status or "").lower() in _JOB_OK


# Anthropic computer-tool action names -> the desktop agent's action vocabulary (same names, normalised).
ACTIONS = {"left_click": "click", "click": "click", "right_click": "right_click", "double_click": "double_click",
           "middle_click": "middle_click", "mouse_move": "move", "left_click_drag": "drag", "type": "type",
           "key": "key", "scroll": "scroll", "wait": "wait", "screenshot": "screenshot", "click_mark": "click_mark"}


def to_action(tool_input: dict) -> dict:
    """Normalise one computer-tool call into {type, ...} for the agent. Unknown shapes become a harmless screenshot."""
    a = str(tool_input.get("action") or tool_input.get("type") or "").lower()
    if a in ("done", "finish", "complete"):
        return {"type": "done", "answer": str(tool_input.get("text") or tool_input.get("answer") or "")}
    if a == "needs_login":
        return {"type": "needs_login"}
    t = ACTIONS.get(a)
    if not t:
        return {"type": "screenshot"}
    out: dict = {"type": t}
    c = tool_input.get("coordinate") or tool_input.get("coordinates")
    if isinstance(c, (list, tuple)) and len(c) >= 2:
        out["x"], out["y"] = float(c[0]), float(c[1])
    if tool_input.get("start_coordinate"):
        s = tool_input["start_coordinate"]
        out["from_x"], out["from_y"] = float(s[0]), float(s[1])
    if t == "type":
        out["text"] = str(tool_input.get("text") or "")
    if t == "key":
        out["key"] = str(tool_input.get("text") or tool_input.get("key") or "Return")
    if t == "scroll":
        n = float(tool_input.get("scroll_amount") or 3)
        d = str(tool_input.get("scroll_direction") or "down").lower()
        out["dy"] = (-n if d == "up" else n) * 100 if d in ("up", "down") else 0
        out["dx"] = (-n if d == "left" else n) * 100 if d in ("left", "right") else 0
    if t == "wait":
        out["seconds"] = min(float(tool_input.get("duration") or 1), 10)
    if tool_input.get("element_id") is not None or tool_input.get("mark") is not None:
        out["type"] = "click_mark"
        out["element_id"] = int(tool_input.get("element_id") or tool_input.get("mark"))
    return out


PROMPT = ("You control the user's own computer through its screen. GOAL: {goal}\n"
          "Screen size (w,h): {size}. UI elements (set-of-mark): {elements}\nActions so far: {history}\n"
          "Prefer {{\"element_id\":<number>}} to click numbered pink marks; use x,y only if no mark fits. "
          "If the task needs sign-in, captcha, payment or an unknown password, answer {{\"type\":\"needs_login\"}}. "
          "When the goal is met answer {{\"type\":\"done\",\"answer\":\"<result>\"}}. "
          "One JSON object only: {{\"type\":\"click_mark|click|type|key|scroll|wait|screenshot|done|needs_login\","
          "\"element_id\":..,\"x\":..,\"y\":..,\"text\":..,\"key\":..,\"dy\":..}}")


class ComputerUse:
    def __init__(self, svc, settings=None):
        self.svc, self.settings = svc, settings

    async def plan(self, goal: str, shot_b64: str, size: list, history: list, elements: list | None = None) -> dict:
        elements = elements or []
        ep = resolve_vm_vision(settings=self.settings)
        if not vision_ready(ep):
            raise RuntimeError("no vision provider configured (Bedrock AWS credentials or VM_VISION_API_KEY)")
        if ep.provider == "bedrock":
            try:
                return await self._bedrock(ep, goal, shot_b64, size, history, elements)
            except Exception as e:
                log.info("native computer-use call failed, falling back to JSON vision: %s", e)
        raw = await vision_complete(ep, PROMPT.format(goal=goal, size=size, elements=json.dumps(elements[-24:]),
                                                    history=json.dumps(history[-6:])),
                                    shot_b64, max_tokens=300)
        try:
            return to_action(json.loads(raw[raw.find("{"): raw.rfind("}") + 1]))
        except ValueError:
            return {"type": "screenshot"}

    async def _bedrock(self, ep, goal, shot_b64, size, history, elements: list) -> dict:
        import asyncio

        import boto3
        client = boto3.client("bedrock-runtime", region_name=ep.region)
        msgs = [{"role": "user", "content": [
            {"text": PROMPT.format(goal=goal, size=size, elements=json.dumps(elements[-24:]),
                                   history=json.dumps(history[-6:]))},
            {"image": {"format": "jpeg", "source": {"bytes": base64.b64decode(shot_b64)}}}]}]
        tools = {"tools": [{"toolSpec": {"name": "computer", "description": "Control the computer screen.",
                 "inputSchema": {"json": {"type": "object", "required": ["action"], "properties": {
                     "action": {"type": "string"}, "coordinate": {"type": "array", "items": {"type": "number"}},
                     "start_coordinate": {"type": "array", "items": {"type": "number"}},
                     "text": {"type": "string"}, "scroll_direction": {"type": "string"},
                     "scroll_amount": {"type": "number"}, "duration": {"type": "number"}}}}}}]}
        extra = {"anthropic_beta": ["computer-use-2025-01-24"],
                 "computer_use": {"display_width_px": int(size[0]), "display_height_px": int(size[1])}}
        resp = await asyncio.to_thread(client.converse, modelId=ep.model, messages=msgs,
                                       inferenceConfig={"maxTokens": 400, "temperature": 0},
                                       toolConfig=tools, additionalModelRequestFields=extra)
        for b in resp.get("output", {}).get("message", {}).get("content") or []:
            tu = b.get("toolUse")
            if tu and str(tu.get("name")).lower() in ("computer", "computer_use"):
                return to_action(tu.get("input") or {})
            if b.get("text") and "{" in b["text"]:
                try:
                    return to_action(json.loads(b["text"][b["text"].find("{"): b["text"].rfind("}") + 1]))
                except ValueError:
                    pass
        raise RuntimeError("no computer action in the model reply")

    async def run(self, user_id: str, device_id: str, goal: str, conv: str | None, max_steps: int = 15,
                  on_frame=None) -> dict:
        if not goal.strip():
            return {"status": "failed", "error": "goal is required"}
        history: list = []
        action: dict = {"type": "screenshot"}
        for _ in range(max(1, min(max_steps, 40))):
            jid = await self.svc.submit(user_id, device_id, "cua", {"action": action}, conv)
            j = await self.svc.wait(jid, 90)
            status = (j or {}).get("status", "failed")
            if not job_succeeded(status):
                return {"status": status, "error": (j or {}).get("error"), "steps": history}
            res = j["result"] or {}
            shot = res.get("screenshot_b64")
            if not shot:
                return {"status": "failed", "error": "no screenshot from the computer", "steps": history}
            if on_frame:
                await on_frame(user_id, shot)
            action = await self.plan(goal, shot, res.get("size") or [1280, 800], history, res.get("elements") or [])
            history.append({k: v for k, v in action.items() if k != "text" or len(str(v)) < 80})
            if action["type"] == "done":
                return {"status": "done", "answer": action.get("answer", ""), "steps": history}
            if action["type"] == "needs_login":
                return {"status": "needs_login", "steps": history}
        return {"status": "failed", "error": "step budget used", "steps": history}
