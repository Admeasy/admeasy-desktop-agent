import time

from admeasy_desktop.agent_session import AgentSession, COMPUTER_USE_KINDS, OBJECTIVE_IDLE_OFF_S


def test_computer_job_turns_active_on_and_off():
    s = AgentSession()
    assert not s.active
    s.job_started("cua")
    assert s.active
    assert s.pulse
    s.job_finished("cua")
    assert not s.active


def test_status_job_does_not_activate_border():
    s = AgentSession()
    s.job_started("status")
    assert not s.active
    s.job_finished("status")
    assert not s.active


def test_approval_wait_keeps_active_without_pulse():
    s = AgentSession()
    s.job_started("browser")
    s.set_approval_wait(True)
    assert s.active
    assert not s.pulse
    s.set_approval_wait(False)
    assert s.pulse


def test_queued_job_shows_active():
    s = AgentSession()
    s.job_enqueued()
    assert s.active
    s.job_dequeued()
    assert not s.active


def test_objective_idle_expires(monkeypatch):
    s = AgentSession()
    s.track_objective(True)
    assert s.active
    t0 = time.monotonic()

    def fake_monotonic():
        return t0 + OBJECTIVE_IDLE_OFF_S + 1

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    assert not s.active


def test_computer_use_kinds_exclude_status():
    assert "status" not in COMPUTER_USE_KINDS
    assert "cua" in COMPUTER_USE_KINDS
