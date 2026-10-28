"""Live contract checks against Lightsail (no user JWT required for most tests)."""
from __future__ import annotations

import httpx
import pytest

BACKEND = "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"

pytestmark = pytest.mark.live_backend


@pytest.fixture(scope="module")
def live():
    try:
        httpx.get(BACKEND + "/health", timeout=15).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"live backend unreachable: {exc}")
    return BACKEND


def test_openapi_lists_desktop_routes(live):
    spec = httpx.get(live + "/openapi.json", timeout=20).json()
    paths = spec.get("paths") or {}
    for path in (
        "/conversations",
        "/devices/pair-codes",
        "/devices/pair/redeem",
        "/reminders",
        "/push/vapid-public-key",
        "/push/web",
        "/employees",
        "/me/triggers",
        "/oauth/connections",
        "/activity",
    ):
        assert path in paths, path


def test_vapid_public_key_is_exposed(live):
    r = httpx.get(live + "/push/vapid-public-key", timeout=10)
    r.raise_for_status()
    body = r.json()
    assert body.get("public_key")


def test_pair_codes_require_jwt(live):
    r = httpx.post(live + "/devices/pair-codes", json={"client": "desktop"}, timeout=10)
    assert r.status_code == 401


def test_reminders_list_requires_auth(live):
    r = httpx.get(live + "/reminders", timeout=10)
    assert r.status_code in (401, 403)


def test_chat_ws_rejects_missing_client(live):
    """Prod should require client=desktop on /ws/session (handshake fails fast)."""
    import asyncio
    import websockets

    async def probe():
        url = live.replace("https://", "wss://") + "/ws/session?token=invalid"
        try:
            async with websockets.connect(url, open_timeout=8):
                return "connected"
        except Exception as exc:
            return str(exc)

    result = asyncio.run(probe())
    assert "connected" not in result
