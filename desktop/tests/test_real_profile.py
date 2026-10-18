from types import SimpleNamespace

from admeasy_desktop.real_profile import resolve


def test_comet_resolves_from_the_json_catalog():
    rp = resolve("comet", SimpleNamespace(), platform="darwin", exists=lambda p: True)
    assert rp["executable"].endswith("Comet.app/Contents/MacOS/Comet")
    assert rp["user_data_dir"].endswith("Library/Application Support/Comet") and rp["source"] == "comet"


def test_settings_override_and_missing_paths():
    s = SimpleNamespace(playwright_executable="/x/browser", playwright_user_data_dir="~/prof")
    assert resolve("", s)["source"] == "settings"
    assert resolve("comet", SimpleNamespace(), platform="darwin", exists=lambda p: False) is None
    assert resolve("safari", SimpleNamespace(), platform="darwin", exists=lambda p: True) is None


def test_hint_comes_from_the_catalog():
    from admeasy_desktop.real_profile import hint_for

    assert hint_for("Comet") == "comet" and hint_for("Google Chrome") == "chrome" and hint_for("Safari") == ""
