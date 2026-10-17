"""HTTP + WebSocket surface for local computers.

POST   /devices/register        signed-in desktop app enrols itself (Bearer user JWT) -> device_id + device_token
GET    /devices                 phone / desktop list of this account's computers, with online state
PATCH  /devices/{id}            rename
DELETE /devices/{id}            revoke (drops the tunnel, token stops working)
POST   /devices/{id}/cancel     kill switch: stop the running job and clear the queue
WS     /devices/tunnel          the desktop agent dials out here (Bearer device_token, X-Device-Id)
GET    /devices/approvals       actions waiting for the user's yes/no (shown on the phone)
POST   /devices/approvals/{id}  answer one: {"allow": true|false}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel

from app.auth import AuthedUser, current_user

api = APIRouter()


def _svc(request: Request):
    svc = getattr(request.app.state, "devices", None)
    if svc is None:
        raise HTTPException(503, "devices are disabled")
    return svc


class RegisterBody(BaseModel):
    name: str
    platform: str  # macos | windows | linux
    os_version: str = ""
    capabilities: dict = {}


class RenameBody(BaseModel):
    name: str


class AnswerBody(BaseModel):
    allow: bool


@api.post("/devices/register")
async def register(body: RegisterBody, request: Request, user: AuthedUser = Depends(current_user)):
    if body.platform not in ("macos", "windows", "linux"):
        raise HTTPException(400, "platform must be macos, windows or linux")
    return await _svc(request).register(user.id, body.name, body.platform, body.os_version, body.capabilities)


@api.get("/devices")
async def list_devices(request: Request, user: AuthedUser = Depends(current_user)):
    return {"devices": await _svc(request).list(user.id)}


@api.patch("/devices/{device_id}")
async def rename(device_id: str, body: RenameBody, request: Request, user: AuthedUser = Depends(current_user)):
    if not await _svc(request).rename(user.id, device_id, body.name):
        raise HTTPException(404, "device not found")
    return {"ok": True}


@api.delete("/devices/{device_id}")
async def revoke(device_id: str, request: Request, user: AuthedUser = Depends(current_user)):
    if not await _svc(request).revoke(user.id, device_id):
        raise HTTPException(404, "device not found")
    return {"ok": True}


@api.post("/devices/{device_id}/cancel")
async def cancel(device_id: str, request: Request, user: AuthedUser = Depends(current_user)):
    svc = _svc(request)
    if not any(d["id"] == device_id for d in await svc.list(user.id)):
        raise HTTPException(404, "device not found")
    await svc.cancel_all(device_id)
    return {"ok": True}


@api.get("/devices/approvals")
async def approvals(request: Request, user: AuthedUser = Depends(current_user)):
    return {"pending": _svc(request).pending_approvals(user.id)}


@api.post("/devices/approvals/{approval_id}")
async def answer(approval_id: str, body: AnswerBody, request: Request, user: AuthedUser = Depends(current_user)):
    if not await _svc(request).answer_approval(user.id, approval_id, body.allow):
        raise HTTPException(404, "approval not found or already answered")
    return {"ok": True}


@api.websocket("/devices/tunnel")
async def tunnel(ws: WebSocket):
    svc = getattr(ws.app.state, "devices", None)
    auth = ws.headers.get("authorization", "")
    dev = ws.headers.get("x-device-id", "")
    who = await svc.authenticate(dev, auth.removeprefix("Bearer ")) if svc else None
    if not who:
        await ws.close(code=4401)
        return
    await ws.accept()
    await svc.on_tunnel(dev, who["user_id"], ws)
