from admeasy_desktop.som import annotate_screenshot, center_for_mark


def test_annotate_and_click_mark():
    shot = {"screenshot_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "size": [640, 480]}
    ax = [{"role": "Button", "name": "Sign in", "x": 10, "y": 20, "w": 80, "h": 30}]
    out = annotate_screenshot(shot, ax, logical_size=(1000, 800))
    assert out["som"] is True
    assert len(out["elements"]) == 1
    assert out["elements"][0]["id"] == 1
    c = center_for_mark(1)
    assert c == (50, 35)
