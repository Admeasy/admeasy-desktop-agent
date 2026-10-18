from admeasy_desktop.executors.screen import type_verdict
from admeasy_desktop.input_darwin import parse_secure_input_pid


def test_ax_text_is_proof():
    assert type_verdict("make an HTML", "make an HTML website", "", None) is True


def test_web_editor_without_ax_uses_pixels():
    assert type_verdict("make an HTML", None, None, True) is True
    assert type_verdict("make an HTML", None, None, False) is False
    assert type_verdict("make an HTML", None, None, None) is None


def test_unchanged_field_is_a_failure():
    assert type_verdict("hello", "", "", None) is False


def test_secure_input_pid_parsed():
    assert parse_secure_input_pid('  | "kCGSSessionSecureInputPID"=412\n') == 412
    assert parse_secure_input_pid('"kCGSSessionSecureInputPID"=0') is None
    assert parse_secure_input_pid("") is None
