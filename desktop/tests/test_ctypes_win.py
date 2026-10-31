from admeasy_desktop import ctypes_win as cw


def test_hcursor_alias():
    assert cw.HCURSOR is cw.HANDLE
