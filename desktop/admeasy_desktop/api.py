"""HTTP helpers against the Admeasy backend (admeasy-ai-assistant main device API)."""
from __future__ import annotations

import httpx

DEVICES_DISABLED = "devices are disabled on the backend (set DEVICES_ENABLED=true)"
DEVICES_NOT_DEPLOYED = (
    "device routes not found on this backend host (404). Deploy admeasy-ai-assistant main "
    "with DEVICES_ENABLED=true to the URL in ADMEASY_BACKEND."
)


class DevicesDisabledError(Exception):
    """Raised when the API returns 503 because DEVICES_ENABLED is false."""


class DevicesNotDeployedError(Exception):
    """Raised when /devices returns 404 (older image or wrong host)."""


def devices_api_state(backend: str, access_token: str | None = None) -> str:
    """ok | disabled | not_deployed | unreachable | auth_required."""
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        r = httpx.get(f"{backend.rstrip('/')}/devices", headers=headers, timeout=8)
    except httpx.HTTPError:
        return "unreachable"
    if r.status_code == 503:
        return "disabled"
    if r.status_code == 404:
        return "not_deployed"
    if r.status_code == 401:
        return "auth_required"
    if r.status_code == 200:
        return "ok"
    return "unreachable"


def check_devices_enabled(backend: str, access_token: str | None = None) -> bool:
    return devices_api_state(backend, access_token) in ("ok", "auth_required")


def raise_for_devices(r: httpx.Response) -> None:
    if r.status_code == 503:
        raise DevicesDisabledError(DEVICES_DISABLED)
    if r.status_code == 404:
        raise DevicesNotDeployedError(DEVICES_NOT_DEPLOYED)
