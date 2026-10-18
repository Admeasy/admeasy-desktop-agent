from admeasy_desktop.screen_coords_mac import window_top_left_for_center


def test_window_top_left_matches_pyautogui_space():
    tl_x, tl_y = window_top_left_for_center(200.0, 300.0, 28.0)
    assert tl_x == 186.0
    assert tl_y == 286.0
