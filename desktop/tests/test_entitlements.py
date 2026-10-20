"""Invite gate and plan checks. Limits come from the payload, never from constants in the client."""
import json
import threading
import urllib.parse
import urllib.request

import httpx
import pytest

from admeasy_desktop import auth
from admeasy_desktop.agent import Agent
from admeasy_desktop.config import Settings
from admeasy_desktop.entitlements import (
    COMPUTER_USE_ACTION,
    UPGRADE_URL,
    AccountEntitlements,
    EntitlementsClient,
    InviteError,
    feature_message,
    limit_message,
    parse_me,
    parse_usage,
)
from admeasy_desktop.ui.server import UiState, serve


pytestmark = pytest.mark.no_entitlement_stub


def test_founder_and_friend_accounts_are_invited_and_limits_are_copied():
    free = parse_me({
        "effective_plan": "free",
        "referred_by": "1111",
        "referred_by_founder": True,
        "payment_method_on_file": False,
        "referral": None,
        "usage": {"cursor": {"used": 2, "limit": 30, "remaining": 28, "period": "week"}},
    })
    assert free.invited and free.plan_family == "free"
    assert free.allows("local_machine")
    assert not free.allows("virtual_machine")
    assert not free.allows("claude") and not free.allows("vision")
    assert free.usage["remaining"] == 28 and free.usage["limit"] == 30
    assert "claude" not in free.models

    starter = parse_me({
        "plan": "starter_monthly",
        "referred_by": "friend",
        "referral": {"code": "AB12", "remaining": 7, "cap": 10},
        "usage": {"cursor": {"remaining": 3, "limit": 80, "period": "week"}},
    })
    assert starter.invited and starter.plan_family == "starter" and starter.plan_name == "Starter"
    assert starter.allows("virtual_machine") and starter.allows("local_machine")
    assert not starter.allows("claude") and not starter.allows("vision")
    assert starter.referral == {"code": "AB12", "remaining": 7, "cap": 10}
    assert starter.usage["remaining"] == 3 and starter.usage["limit"] == 80

    pro = parse_me({
        "plan": "pro_monthly",
        "invited": True,
        "features": {"local_machine": True, "virtual_machine": True, "claude": True, "vision": True, "deep_agents": True},
        "referral": {"code": "PRO20", "remaining": 19, "cap": 20},
        "models": ["claude", "sarvam", "groq"],
    })
    assert pro.allows("claude") and pro.allows("vision") and pro.allows("deep_agents")
    assert pro.models[0] == "claude"
    assert pro.referral["cap"] == 20


def test_signed_in_account_without_an_invite_is_blocked():
    snap = parse_me({"plan": "free", "referred_by_founder": False, "referred_by": None, "referral": None})
    assert not snap.invited
    assert not snap.allows("claude")


def test_explicit_feature_map_wins_over_the_plan_name():
    snap = parse_me({
        "plan": "pro",
        "invited": True,
        "features": {"claude": False, "vision": False, "local_machine": True, "virtual_machine": True},
    })
    assert snap.plan_family == "pro"
    assert not snap.allows("claude") and snap.allows("local_machine")


def test_validate_invite_accepts_founder_code_and_rejects_junk():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        code = (body.get("code") or "").strip()
        if code in ("1111", "#1111"):
            return httpx.Response(200, json={
                "valid": True, "kind": "founder", "normalized_code": "1111",
                "referrer": {"id": None, "label": "founder"},
            })
        if not code:
            return httpx.Response(400, json={"error": "invite_required", "detail": "Enter an invite code."})
        return httpx.Response(404, json={"error": "invite_invalid", "detail": "That invite code isn't valid."})

    client = EntitlementsClient("https://api.example", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.validate_invite("#1111").normalized_code == "1111"
    assert client.validate_invite("  1111 ").kind == "founder"
    with pytest.raises(InviteError) as empty:
        client.validate_invite("   ")
    assert empty.value.code == "invite_required"
    with pytest.raises(InviteError) as bad:
        client.validate_invite("nope")
    assert "isn't valid" in str(bad.value)


def test_usage_check_posts_the_cursor_pool_and_reads_the_decision():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        if request.url.path.endswith("/usage/check"):
            return httpx.Response(200, json={
                "allowed": False, "action": "cursor", "error": "usage_limit",
                "detail": "Weekly computer actions are used up",
                "remaining": 0, "limit": 15,
            })
        return httpx.Response(200, json={"invited": True, "plan": "free", "referred_by": "1111"})

    client = EntitlementsClient("https://api.example", http=httpx.Client(transport=httpx.MockTransport(handler)))
    client._bearer = lambda: "tok"
    decision = client.usage_check()
    assert seen["path"] == "/entitlements/usage/check"
    assert seen["body"] == {"action": COMPUTER_USE_ACTION}
    assert seen["auth"] == "Bearer tok"
    assert not decision.allowed and decision.is_limit
    assert decision.remaining == 0 and decision.limit == 15
    snap = AccountEntitlements.allow_all()
    text = limit_message(decision, snap)
    assert UPGRADE_URL in text and "used up" in text


def test_usage_denied_with_http_429_is_a_limit():
    decision = parse_usage(429, {"detail": "slow down", "remaining": 0}, "cursor")
    assert not decision.allowed and decision.is_limit
    assert "slow down" in decision.message


@pytest.mark.asyncio
async def test_computer_use_stops_when_the_weekly_pool_is_empty(tmp_path):
    agent = Agent(Settings(backend="http://127.0.0.1:9", shared_folders=[str(tmp_path)], approval_mode="trusted"))
    calls = []

    class Gate:
        def me(self, fresh=False):
            return parse_me({
                "plan": "free", "invited": True, "referred_by": "1111",
                "usage": {"cursor": {"remaining": 0, "limit": 5, "period": "week"}},
            })

        def usage_check(self, action):
            calls.append(action)
            return parse_usage(200, {
                "allowed": False, "error": "usage_limit", "remaining": 0, "limit": 5,
                "detail": "Weekly computer actions are used up",
            }, action)

    agent.entitlements = Gate()
    sent = []

    async def send(msg):
        sent.append(msg)

    agent.send = send
    await agent.run_job({"job_id": "j1", "kind": "shell", "params": {"command": "echo hi"}})
    assert calls == ["cursor"]
    assert sent[0]["status"] == "rate_limited"
    assert UPGRADE_URL in sent[0]["error"]
    assert "output" not in sent[0]


@pytest.mark.asyncio
async def test_claude_on_starter_is_refused_before_it_runs(tmp_path):
    agent = Agent(Settings(backend="http://127.0.0.1:9", shared_folders=[str(tmp_path)], approval_mode="trusted"))
    calls = []

    class Gate:
        def me(self, fresh=False):
            return parse_me({"plan": "starter_monthly", "referred_by": "1111"})

        def usage_check(self, action):
            calls.append(action)
            return parse_usage(200, {"allowed": True}, action)

    agent.entitlements = Gate()
    sent = []

    async def send(msg):
        sent.append(msg)

    agent.send = send
    await agent.run_job({"job_id": "j1", "kind": "cli", "params": {"op": "run", "profile": "claude", "prompt": "hi"}})
    assert calls == []
    assert sent[0]["status"] == "blocked"
    assert "Claude" in sent[0]["error"] and UPGRADE_URL in sent[0]["error"]
    assert sent[0]["result"]["feature"] == "claude"


@pytest.mark.asyncio
async def test_allowed_computer_use_still_runs(tmp_path):
    agent = Agent(Settings(backend="http://127.0.0.1:9", shared_folders=[str(tmp_path)], approval_mode="trusted"))

    class Gate:
        def me(self, fresh=False):
            return parse_me({"plan": "free", "invited": True, "referred_by": "1111"})

        def usage_check(self, action):
            return parse_usage(200, {"allowed": True, "remaining": 4, "limit": 5}, action)

    agent.entitlements = Gate()
    sent = []

    async def send(msg):
        sent.append(msg)

    agent.send = send
    await agent.run_job({"job_id": "j1", "kind": "shell", "params": {"command": "echo hi"}})
    result = next(m for m in sent if m.get("type") == "result")
    assert result["status"] == "ok"
    assert "hi" in result["result"]["output"]


def test_pro_advertises_claude_and_free_does_not():
    agent = Agent(Settings())
    assert "claude" not in agent.capabilities()["cli_profiles"]
    assert agent.capabilities()["plan"]["vision"] is False
    agent._snap = parse_me({"plan": "pro_monthly", "invited": True})
    caps = agent.capabilities()
    assert "claude" in caps["cli_profiles"]
    assert caps["plan"]["vision"] is True
    assert "claude" in caps["plan"]["models"]


def test_google_start_carries_the_normalized_invite(monkeypatch):
    def fake_browser(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        assert q["invite"] == "1111"
        base = f"http://127.0.0.1:{q['desktop_port']}/callback?"

        def go():
            urllib.request.urlopen(base + urllib.parse.urlencode(
                {"access_token": "a", "refresh_token": "r", "email": "x@y.z", "nonce": q["nonce"]}))
        threading.Thread(target=go, daemon=True).start()

    got = auth.login_via_browser("https://api.example", timeout_s=5, open_browser=fake_browser, invite="1111")
    assert got["email"] == "x@y.z"


def test_window_asks_for_a_code_then_shows_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMEASY_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "HOME", tmp_path)
    monkeypatch.setattr(auth, "_kr", lambda: None)
    state = UiState(Settings(backend="http://127.0.0.1:1"))

    class Gate:
        def validate_invite(self, code):
            if code.strip() in ("1111", "#1111"):
                from admeasy_desktop.entitlements import InviteValidation
                return InviteValidation("1111", "founder")
            raise InviteError("That invite code isn't valid.")

        def me(self, fresh=False):
            return parse_me({
                "plan": "starter_monthly",
                "referred_by": "1111",
                "usage": {"cursor": {"remaining": 11, "limit": 40, "period": "week"}},
                "referral": {"code": "JOIN", "remaining": 9, "cap": 10},
            })

    state.entitlements = Gate()
    srv, port = serve(state)
    try:
        base = f"http://127.0.0.1:{port}"
        first = json.load(urllib.request.urlopen(base + "/api/state"))
        assert first["needs_invite"] and not first["signed_in"]
        urllib.request.urlopen(urllib.request.Request(
            base + "/api/invite",
            data=json.dumps({"code": "nope"}).encode(),
            headers={"Content-Type": "application/json"},
        ))
        rejected = json.load(urllib.request.urlopen(base + "/api/state"))
        assert "isn't valid" in rejected["error"]
        assert not rejected["pending_invite"]
        urllib.request.urlopen(urllib.request.Request(
            base + "/api/invite",
            data=json.dumps({"code": "#1111"}).encode(),
            headers={"Content-Type": "application/json"},
        ))
        accepted = json.load(urllib.request.urlopen(base + "/api/state"))
        assert accepted["pending_invite"] == "1111" and accepted["needs_invite"]

        auth.save_secret("access_token", "a")
        auth.save_secret("refresh_token", "r")
        auth.save_secret("email", "ada@example.com")
        shown = json.load(urllib.request.urlopen(base + "/api/state"))
        assert shown["invited"] and not shown["needs_invite"]
        assert shown["entitlements"]["plan_name"] == "Starter"
        assert shown["entitlements"]["usage"]["remaining"] == 11
        assert shown["entitlements"]["usage"]["limit"] == 40
        assert shown["entitlements"]["referral"]["code"] == "JOIN"
        assert shown["entitlements"]["referral"]["remaining"] == 9
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "https://admeasy.ai" in page
    finally:
        srv.shutdown()


@pytest.mark.asyncio
async def test_status_does_not_spend_the_cursor_pool(tmp_path):
    agent = Agent(Settings(backend="http://127.0.0.1:9", shared_folders=[str(tmp_path)]))
    calls = []

    class Gate:
        def me(self, fresh=False):
            calls.append("me")
            return parse_me({"plan": "free", "invited": True, "referred_by": "1111"})

        def usage_check(self, action):
            calls.append(action)
            return parse_usage(200, {"allowed": False}, action)

    agent.entitlements = Gate()
    sent = []

    async def send(msg):
        sent.append(msg)

    agent.send = send
    await agent.run_job({"job_id": "j-status", "kind": "status", "params": {"domains": []}})
    assert calls == []
    assert sent and sent[0]["status"] == "ok"


def test_feature_copy_names_the_upgrade_site():
    snap = parse_me({"plan": "free", "invited": True, "referred_by": "1111"})
    assert UPGRADE_URL in feature_message("vision", snap)
    assert "vision" in feature_message("vision", snap).lower()
