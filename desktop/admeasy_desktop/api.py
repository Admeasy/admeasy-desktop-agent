"""HTTP helpers against the Admeasy backend (matches admeasy-ai-assistant PR #42 device API)."""
from __future__ import annotations

import httpx

DEVICES_DISABLED = "devices are disabled on the backend (set DEVICES_ENABLED=true)"


class DevicesDisabledError(Exception):
    """Raised when the API returns 503 because DEVICES_ENABLED is false."""


def check_devices_enabled(backend: str, access_token: str | None = None) -> bool:
    """True if GET /devices is available (not 503). Uses user JWT when provided."""
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        r = httpx.get(f"{backend.rstrip('/')}/devices", headers=headers, timeout=8)
    except httpx.HTTPError:
        return False
    if r.status_code == 503:
        return False
    return r.status_code in (200, 401)


def raise_for_devices(r: httpx.Response) -> None:
    if r.status_code == 503:
        raise DevicesDisabledError(DEVICES_DISABLED)
