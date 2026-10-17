from admeasy_desktop.input_darwin import _keycode


def test_keycode_v():
    assert _keycode("v") == 9
    assert _keycode("return") == 36
