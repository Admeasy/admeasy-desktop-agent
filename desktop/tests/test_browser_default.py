import pytest

from admeasy_desktop.executors.browser import Browser


@pytest.mark.asyncio
async def test_default_first_read_uses_screen(monkeypatch):
    monkeypatch.setattr(
        "admeasy_desktop.config.Settings.load",
        lambda: type("S", (), {"browser_automation": "default_first"})(),
    )
    monkeypatch.setattr("admeasy_desktop.executors.app_launch.open_url_default", lambda u: None)

    async def fake_shot(chars=4000):
        return {"url": "", "title": "", "text": "", "screenshot_b64": "AA==", "size": [10, 10], "surface": "screen"}

    monkeypatch.setattr("admeasy_desktop.executors.browser._screen_snapshot", fake_shot)
    b = Browser()
    out = await b.run({"op": "read", "url": "https://example.com", "settle_s": 0})
    assert out["status"] == "done"
    assert out["result"]["surface"] == "screen"
