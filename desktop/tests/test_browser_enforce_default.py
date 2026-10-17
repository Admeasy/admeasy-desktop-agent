from admeasy_desktop.executors.browser import _automation_mode


def test_playwright_only_with_force():
    assert _automation_mode({}) == "default_first"
    assert _automation_mode({"force_playwright": True}) == "playwright_profile"


def test_config_migrates_playwright_profile(tmp_path, monkeypatch):
    from admeasy_desktop.config import Settings

    monkeypatch.setattr("admeasy_desktop.config.HOME", tmp_path)
    monkeypatch.setattr("admeasy_desktop.config.CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"browser_automation": "playwright_profile"}')
    s = Settings.load()
    assert s.browser_automation == "default_first"


def test_whatsapp_no_auto_web(monkeypatch):
    from admeasy_desktop.executors import whatsapp_exec

    monkeypatch.setattr(
        "admeasy_desktop.config.Settings.load",
        lambda: type("S", (), {"browser_automation": "playwright_profile"})(),
    )
    monkeypatch.setattr("admeasy_desktop.executors.whatsapp_exec.launch", lambda n: {"status": "done", "result": {}})
    async def _shot(settle=2.5):
        return {"status": "done", "result": {"surface": "whatsapp_desktop"}}

    monkeypatch.setattr("admeasy_desktop.executors.whatsapp_exec._desktop_shot", _shot)

    import asyncio

    out = asyncio.run(whatsapp_exec.run({"op": "open"}))
    assert out["result"]["surface"] == "whatsapp_desktop"
