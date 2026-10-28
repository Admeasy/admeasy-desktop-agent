from pathlib import Path

from admeasy_desktop.ui.paths import ui_dir


def test_ui_dir_contains_app_assets():
    root = ui_dir()
    for name in ("index.html", "app.js", "theme.css", "sw.js", "manifest.webmanifest"):
        assert (root / name).is_file(), name


def test_auth_file_store_roundtrip(tmp_path, monkeypatch):
    from admeasy_desktop import auth, config

    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setenv("ADMEASY_SECRETS", "file")
    auth.save_secrets({"access_token": "a", "refresh_token": "r"})
    assert auth.load_secret("access_token") == "a"
    assert (tmp_path / "secrets.json").is_file()
