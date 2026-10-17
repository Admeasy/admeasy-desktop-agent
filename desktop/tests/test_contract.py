from admeasy_desktop import auth
from admeasy_desktop.api import devices_api_state
from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings
from admeasy_desktop.permissions import wire_snapshot


def test_sign_in_nonce_max_64_chars():
    for _ in range(20):
        assert len(auth._sign_in_nonce()) <= 64


def test_loopback_port_in_backend_range():
    for _ in range(10):
        p = auth._free_port()
        assert 1024 <= p <= 65535


def test_hello_wire_fields():
    a = Agent(Settings())
    caps = a.capabilities()
    hello = {"type": "hello", "version": "0", "os_version": "x", "capabilities": caps,
             "permissions": wire_snapshot()}
    assert set(hello) >= {"type", "version", "os_version", "capabilities", "permissions"}
    assert set(hello["permissions"]) <= {"screen", "accessibility"}


def test_devices_api_state_interpretation():
    assert devices_api_state("http://127.0.0.1:1") == "unreachable"


def test_approval_request_field_limits():
    from admeasy_desktop.policy import judge
    v = judge("shell", {"command": "echo hi"}, "ask_risky", [])
    action = "shell"
    summary = "x" * 500
    risk = "high"
    assert len(action) <= 80
    assert len(summary[:400]) == 400
    assert len(risk[:20]) == 4
