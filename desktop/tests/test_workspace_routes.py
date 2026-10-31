"""Backend proxy routes for workspace hub APIs."""
from __future__ import annotations

from admeasy_desktop.config import Settings
from admeasy_desktop.ui.backend_routes import handle_backend_get, handle_backend_post


class _State:
    def __init__(self):
        self.settings = Settings(backend="https://example.test")


def test_backend_get_workspace_paths(monkeypatch):
    calls = []

    def fake_request(method, path, **kw):
        calls.append((method, path, kw.get("params")))
        return {"ok": True}

    import admeasy_desktop.ui.backend_routes as mod

    monkeypatch.setattr(mod.BackendClient, "request", lambda self, method, path, **kw: fake_request(method, path, **kw))
    st = _State()
    assert handle_backend_get(st, "schedules") == {"ok": True}
    assert handle_backend_get(st, "schedules/abc") == {"ok": True}
    assert handle_backend_get(st, "kb/documents") == {"ok": True}
    assert handle_backend_get(st, "kb/documents/doc-1") == {"ok": True}
    assert handle_backend_get(st, "vault/overview") == {"ok": True}
    assert handle_backend_get(st, "mcp/connectors/slack") == {"ok": True}
    assert calls[1][1] == "/schedules/abc"
    assert calls[1][2] == {"run_limit": 40}


def test_backend_post_kb_upload(monkeypatch):
    body = None

    def fake_request(self, method, path, **kw):
        nonlocal body
        body = (method, path, kw.get("json_body"))
        return {"id": "new"}

    import admeasy_desktop.ui.backend_routes as mod

    monkeypatch.setattr(mod.BackendClient, "request", fake_request)
    st = _State()
    payload = {"title": "t", "text": "hello", "kind": "markdown", "ai_generated": False}
    out = handle_backend_post(st, "kb/documents/upload", payload)
    assert out == {"id": "new"}
    assert body[0] == "POST"
    assert body[1] == "/kb/documents/upload"
