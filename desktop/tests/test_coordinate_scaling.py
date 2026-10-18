from admeasy_desktop.coordinate_scaling import Scaler


def test_retina_2x_center_mapping():
    sc = Scaler(logical=(1512, 982), physical=(3024, 1964))
    assert sc.w <= 1280
    x, y = sc.to_logical(sc.w / 2, sc.h / 2)
    assert abs(x - 756) <= 2
    assert abs(y - 491) <= 2


def test_retina_corner_clamps():
    sc = Scaler(logical=(1512, 982), physical=(3024, 1964))
    x, y = sc.to_logical(10**6, 10**6)
    assert x >= sc.lw - 2
    assert y >= sc.lh - 2


def test_secondary_monitor_origin_offset():
    """Screenshot space 1280x800 on primary; logical click lands on secondary (+1920 x)."""
    sc = Scaler(logical=(1280, 800), physical=(1280, 800), monitor_origin=(1920, 0))
    x, y = sc.to_logical(100, 200)
    assert x == 2020
    assert y == 200
