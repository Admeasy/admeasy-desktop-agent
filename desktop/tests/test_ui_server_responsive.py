"""Loopback UI must stay responsive under concurrent /api/state load."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from unittest import mock

import pytest

from admeasy_desktop.config import Settings
from admeasy_desktop.ui.server import UiState, serve


def test_root_responds_while_snapshot_waits_on_network(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMEASY_HOME", str(tmp_path))
    ui = UiState(Settings())
    block = threading.Event()

    def slow_entitlements(*a, **kw):
        block.wait(timeout=5)
        return None

    monkeypatch.setattr(ui, "_load_entitlements", slow_entitlements)
    ui._ent_cache = mock.Mock(invited=True, public=lambda: {"invited": True, "plan": "pro"})
    srv, port = serve(ui)
    base = f"http://127.0.0.1:{port}"

    def poll_state():
        try:
            urllib.request.urlopen(base + "/api/state", timeout=10)
        except Exception:
            pass
        finally:
            block.set()

    threading.Thread(target=poll_state, daemon=True).start()
    time.sleep(0.05)
    t0 = time.monotonic()
    with urllib.request.urlopen(base + "/", timeout=2) as res:
        html = res.read().decode()
        assert res.status == 200
        assert "admeasy-ui-root" in html or 'id="app"' in html
    assert (time.monotonic() - t0) < 1.5
    srv.shutdown()


def test_ping_is_fast():
    ui = UiState(Settings())
    srv, port = serve(ui)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as res:
            data = json.load(res)
            assert data.get("ok") is True
    finally:
        srv.shutdown()
