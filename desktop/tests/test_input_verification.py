import sys
import types

from admeasy_desktop.coordinate_scaling import Scaler
from admeasy_desktop.executors import screen


def test_scaler_uses_monitor_origin_and_retina_scale():
    sc = Scaler((1512, 982), (3024, 1964), monitor_origin=(1512, 0))
    x, y = sc.to_logical(sc.w / 2, sc.h / 2)
    assert abs(x - (1512 + 756)) <= 2 and abs(y - 491) <= 2


def test_scaler_for_shot_geometry():
    shot = {"size": [1280, 831], "geometry": {"logical": [1512, 982], "physical": [3024, 1964], "origin": [0, 0]}}
    sc = screen.scaler_for(shot)
    assert sc.w == 1280 and sc.to_logical(1279, 830)[0] >= 1500


def test_changed_detection():
    a = bytes([10] * 1024)
    assert screen._changed(a, a) is False
    assert screen._changed(a, bytes([200] * 1024)) is True
    assert screen._changed(None, a) is None


def test_verify_click_exception_is_failure(monkeypatch):
    from admeasy_desktop import input_darwin

    def boom():
        raise RuntimeError("no quartz")

    monkeypatch.setattr(input_darwin, "pointer_position", boom)
    assert input_darwin.verify_click(1, 1) is False


def test_typing_falls_back_to_unicode_when_paste_did_not_land(monkeypatch):
    from admeasy_desktop import input_darwin

    values = iter(["", "", "hello"])  # before paste, after paste (unchanged), after unicode retype
    monkeypatch.setattr(screen, "_use_quartz", lambda: True)
    monkeypatch.setattr(screen, "paste_text", lambda t: None)
    monkeypatch.setattr(input_darwin, "focused_value", lambda: next(values))
    typed = []
    monkeypatch.setattr(input_darwin, "type_unicode", lambda t: typed.append(t))
    out = screen.type_text_verified("hello")
    assert out == {"typed_ok": True, "typed_via": "unicode"} and typed == ["hello"]


def test_unknown_action_is_an_error(monkeypatch):
    import pytest
    monkeypatch.setattr(screen, "_pg", lambda: types.SimpleNamespace(size=lambda: (100, 100)))
    with pytest.raises(ValueError):
        screen.act({"type": "teleport"}, Scaler((100, 100), (100, 100)))
