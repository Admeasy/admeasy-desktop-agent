"""Contract checks against the live Lightsail backend. Skips if the host is unreachable."""
import httpx
import pytest

from admeasy_desktop.entitlements import EntitlementsClient, InviteError

BACKEND = "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"
pytestmark = pytest.mark.live_entitlements


@pytest.fixture(scope="module")
def live():
    try:
        httpx.get(BACKEND + "/health", timeout=15).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"live backend unreachable: {exc}")
    return EntitlementsClient(BACKEND)


def test_openapi_lists_entitlement_routes():
    try:
        spec = httpx.get(BACKEND + "/openapi.json", timeout=20).json()
    except httpx.HTTPError as exc:
        pytest.skip(f"openapi unreachable: {exc}")
    paths = spec.get("paths") or {}
    for path in (
        "/entitlements/invites/validate",
        "/entitlements/plans",
        "/entitlements/me",
        "/entitlements/usage/check",
    ):
        assert path in paths
    params = paths["/auth/google/start"]["get"].get("parameters") or []
    assert any(p.get("name") == "invite" for p in params)


def test_plans_catalog_is_the_three_plan_list(live):
    plans = live.plans()
    ids = [p.get("id") for p in plans]
    assert "free" in ids and "starter_monthly" in ids and "pro_monthly" in ids
    for plan in plans:
        assert plan.get("name") and isinstance(plan.get("features"), list) and plan["features"]


def test_founder_code_validates_and_junk_does_not(live):
    assert live.validate_invite("1111").normalized_code == "1111"
    # The live catalog has called this both "founder" and "founder_starter".
    assert live.validate_invite("#1111").kind in {"founder", "founder_starter"}
    with pytest.raises(InviteError) as bad:
        live.validate_invite("nope")
    assert bad.value.code == "invite_invalid"
    assert "isn't valid" in str(bad.value)


def test_usage_check_requires_a_bearer_token(live):
    response = httpx.post(BACKEND + "/entitlements/usage/check", json={"action": "cursor"}, timeout=20)
    assert response.status_code == 401
    me = httpx.get(BACKEND + "/entitlements/me", timeout=20)
    assert me.status_code == 401
