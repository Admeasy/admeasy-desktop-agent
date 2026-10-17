from admeasy_desktop.extension_identity import ALLOWED_ORIGIN, EXTENSION_ID


def test_stable_extension_id():
    assert EXTENSION_ID == "apkfeonhbjpaplapnadecelcljpknplc"
    assert ALLOWED_ORIGIN == f"chrome-extension://{EXTENSION_ID}/"
