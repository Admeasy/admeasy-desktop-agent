"""Proxy selected backend routes for the loopback UI (JWT stays server-side)."""
from __future__ import annotations

from ..backend_client import BackendClient, BackendError


def _items(payload, keys: tuple[str, ...]) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def handle_backend_get(state, name: str) -> dict | None:
    client = BackendClient(state.settings)
    if name == "push/vapid-public-key":
        return client.request("GET", "/push/vapid-public-key", auth_required=False)
    if name == "employees":
        data = client.request("GET", "/employees")
        return {"employees": _items(data, ("employees", "items", "data")) or data}
    if name.startswith("employees/"):
        rest = name.removeprefix("employees/")
        return client.request("GET", f"/employees/{rest}")
    if name == "connectors":
        return client.request("GET", "/oauth/connections")
    if name == "activity":
        return client.request("GET", "/activity", params={"limit": 40})
    if name == "billing/status":
        return client.request("GET", "/billing/status")
    if name == "billing/plans":
        return client.request("GET", "/billing/plans", auth_required=False)
    if name == "mcp/installed":
        return client.request("GET", "/mcp/installed")
    if name == "mcp/catalog":
        return client.request("GET", "/mcp/catalog", auth_required=False)
    return None


def handle_backend_post(state, name: str, body: dict) -> dict | None:
    client = BackendClient(state.settings)
    if name == "push/web":
        return client.request("POST", "/push/web", json_body=body)
    if name == "employees":
        return client.request("POST", "/employees", json_body=body)
    if name.startswith("employees/") and name.endswith("/runs"):
        raise BackendError("use GET for employee runs", 405)
    if name.startswith("employees/") and name.endswith("/pause"):
        eid = name.removeprefix("employees/").removesuffix("/pause")
        return client.request("POST", f"/employees/{eid}/pause", json_body=body or {})
    if name.startswith("employees/") and name.endswith("/resume"):
        eid = name.removeprefix("employees/").removesuffix("/resume")
        return client.request("POST", f"/employees/{eid}/resume", json_body=body or {})
    if name == "triggers":
        return client.request("POST", "/me/triggers", json_body=body)
    if name.startswith("triggers/") and name.endswith("/run"):
        tid = name.removeprefix("triggers/").removesuffix("/run")
        return client.request("POST", f"/triggers/{tid}", json_body=body or {})
    if name.startswith("mcp/connect"):
        return client.request("GET" if body.get("method") == "GET" else "POST", "/mcp/connect", json_body=body)
    if name == "pair-code":
        return client.request("POST", "/devices/pair-codes", json_body={"client": "desktop"})
    return None


def handle_backend_delete(state, name: str) -> dict | None:
    client = BackendClient(state.settings)
    if name.startswith("employees/"):
        eid = name.removeprefix("employees/")
        return client.request("DELETE", f"/employees/{eid}")
    return None


def backend_error_response(exc: BackendError) -> tuple[dict, int]:
    msg = str(exc)
    if isinstance(exc.detail, dict) and exc.detail.get("detail"):
        d = exc.detail["detail"]
        msg = d if isinstance(d, str) else str(d)
    return {"error": msg, "status": exc.status}, exc.status or 400
