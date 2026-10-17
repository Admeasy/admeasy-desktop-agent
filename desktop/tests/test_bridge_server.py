import json

from admeasy_desktop.bridge_server import ADDR_FILE, BRIDGE_ROOT, start, stop


def test_bridge_server_writes_addr_file(tmp_path, monkeypatch):
    stop()
    monkeypatch.setattr("admeasy_desktop.bridge_server.BRIDGE_ROOT", tmp_path)
    monkeypatch.setattr("admeasy_desktop.bridge_server.ADDR_FILE", tmp_path / "agent_addr.json")
    start()
    assert (tmp_path / "agent_addr.json").is_file()
    meta = json.loads((tmp_path / "agent_addr.json").read_text())
    assert meta["family"] in ("unix", "tcp")
    stop()


def test_install_native_host_uses_real_origin(tmp_path, monkeypatch):
    monkeypatch.setattr("admeasy_desktop.browser_bridge.BRIDGE_ROOT", tmp_path / "bridge")
    monkeypatch.setattr("admeasy_desktop.browser_bridge.EXT_INSTALL_DIR", tmp_path / "extension")
    monkeypatch.setattr("admeasy_desktop.browser_bridge.HOST_INSTALL_DIR", tmp_path / "host")
    monkeypatch.setattr("admeasy_desktop.browser_bridge.INSTALL_MARKER", tmp_path / "bridge" / "installed.json")
    monkeypatch.setattr("admeasy_desktop.browser_bridge.open_extension_load_ui", lambda: None)
    monkeypatch.setattr(
        "admeasy_desktop.browser_bridge.native_host_manifest_path",
        lambda b: tmp_path / "nmh" / b,
    )
    from admeasy_desktop.browser_bridge import install_native_host
    from admeasy_desktop.extension_identity import ALLOWED_ORIGIN

    install_native_host()
    manifest = json.loads((tmp_path / "nmh" / "chrome" / "com.admeasy.desktop.json").read_text())
    assert manifest["allowed_origins"] == [ALLOWED_ORIGIN]
    assert (tmp_path / "extension" / "manifest.json").is_file()
