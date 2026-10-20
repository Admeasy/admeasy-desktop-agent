import pytest

from admeasy_desktop import job_store


@pytest.fixture(autouse=True)
def _isolated_job_store(tmp_path, monkeypatch):
    # Every job is cached by key now; tests reuse job ids like "j1", so never share the user's real store.
    monkeypatch.setattr(job_store, "STORE", tmp_path / "job_store.json")


@pytest.fixture(autouse=True)
def _allow_entitlements(monkeypatch, request):
    """Existing tunnel tests drive a stub backend. Live entitlement tests opt out."""
    if request.node.get_closest_marker("live_entitlements") or request.node.get_closest_marker("no_entitlement_stub"):
        return
    from admeasy_desktop import entitlements as ent

    monkeypatch.setattr(
        ent.EntitlementsClient,
        "me",
        lambda self, fresh=False: ent.AccountEntitlements.allow_all(),
    )
    monkeypatch.setattr(
        ent.EntitlementsClient,
        "usage_check",
        lambda self, action="cursor": ent.UsageDecision.allow(action),
    )
