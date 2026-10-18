from admeasy_desktop.ui_settle import wait_for_settle


def test_wait_for_settle_stable_immediately():
    n = 0

    def shot(som=True):
        nonlocal n
        n += 1
        return {"screenshot_b64": "stable"}

    waited = wait_for_settle(shot, max_wait_s=1.0, poll_s=0.05, stable_polls=2)
    assert waited < 0.5
    assert n >= 2
