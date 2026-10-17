from admeasy_desktop.failure_detect import analyze


def test_captcha_from_skill_hint():
    out = analyze([], skill_hints=["Please complete the captcha challenge"])
    assert out and out["status"] == "captcha"


def test_needs_login_when_no_session():
    ax = [{"role": "TextField", "name": "Password"}]
    out = analyze(ax, skill_hints=["Sign in to continue"], session_present=False)
    assert out and out["status"] == "needs_login"
