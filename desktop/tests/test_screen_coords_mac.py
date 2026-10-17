import pytest


@pytest.mark.skipif("sys.platform != 'darwin'", reason="macOS only")
def test_window_top_left_primary_center():
    from admeasy_desktop.screen_coords_mac import window_top_left_for_center

    tl_x, tl_y = window_top_left_for_center(200.0, 300.0, 28.0)
    assert 186.0 <= tl_x <= 214.0
    assert tl_y > 0
