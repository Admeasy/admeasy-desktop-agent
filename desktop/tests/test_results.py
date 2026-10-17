from admeasy_desktop.results import normalize


def test_shell_nonzero_exit_is_error():
    out = normalize("shell", {"status": "ok", "result": {"exit_code": 1, "output": "err"}})
    assert out["status"] == "error"
    assert "code 1" in out["error"]


def test_needs_login_carries_error():
    out = normalize("browser", {"status": "needs_login", "result": {}})
    assert out["status"] == "needs_login"
    assert out.get("error")


def test_open_failure():
    out = normalize("open", {"status": "ok", "error": "could not open"})
    assert out["status"] == "error"
