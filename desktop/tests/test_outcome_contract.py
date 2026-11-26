from admeasy_desktop.outcome import build, wire_status
from admeasy_desktop.results import finalize, normalize


def test_wire_status_mapping():
    assert wire_status("ok") == (True, "done", "ok")
    assert wire_status("needs_login") == (False, "needs_auth", "needs_login")
    assert wire_status("needs_approval") == (False, "needs_approval", "needs_approval")
    assert wire_status("rate_limited") == (False, "rate_limited", "rate_limited")


def test_build_includes_job_id():
    msg = build("ok", job_id="j1", detail="ok", result={"x": 1})
    assert msg["ok"] is True
    assert msg["status"] == "done"
    assert msg["job_id"] == "j1"
    assert msg["result"] == {"x": 1}


def test_finalize_attaches_outcome_fields():
    raw = normalize("shell", {"status": "ok", "result": {"exit_code": 0, "output": "hi"}})
    out = finalize("shell", "job-9", raw)
    assert out["job_id"] == "job-9"
    assert out["ok"] is True
    assert out["status"] == "done"
    assert "detail" in out


def test_exception_maps_to_failed():
    out = finalize("files", "j2", {"status": "error", "error": "ValueError: nope"})
    assert out["ok"] is False
    assert out["status"] == "failed"
    assert out["code"] == "error"