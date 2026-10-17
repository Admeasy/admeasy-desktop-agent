import pytest

from admeasy_desktop.surface_status import collect


def test_status_collect_facts():
    facts = collect({"domains": ["example.com"]})
    assert facts["online"] is True
    assert "permissions" in facts
    assert "permissions_missing" in facts
    assert "default_browser" in facts
    assert "example.com" in facts["sessions"]
    assert "extension_installed" in facts
