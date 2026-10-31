"""Session must expose live_state_block for agent_impl._structured_plan (production parity)."""
from app.agent import Session


def test_session_has_live_state_block_default():
    s = Session("user", "conv")
    assert hasattr(s, "live_state_block")
    assert s.live_state_block == ""


def test_session_live_state_block_assignable():
    s = Session("user", "conv")
    s.live_state_block = "reddit: connected"
    assert s.live_state_block == "reddit: connected"
