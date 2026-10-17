from admeasy_desktop.executors.app_launch import launch, looks_like_url, resolve_app_name


def test_resolve_aliases():
    assert resolve_app_name("whatsapp") == "WhatsApp"
    assert resolve_app_name("cursor") == "Cursor"


def test_looks_like_url():
    assert looks_like_url("https://x.com")
    assert not looks_like_url("WhatsApp")


def test_launch_url(monkeypatch):
    opened = []

    def fake_open(url):
        opened.append(url)

    monkeypatch.setattr("admeasy_desktop.executors.app_launch.open_url_default", fake_open)
    r = launch("https://example.com")
    assert r["status"] == "done"
    assert r["result"]["surface"] == "default_browser"
    assert opened == ["https://example.com"]
