"""Invite gate and plan entitlements for the desktop agent.

The phone app is the command centre. This computer is the "local machine" feature.
Nobody can use it without an invited account. The website flow is the one this app
follows, because sign-in is already the system browser (not a phone pairing code):

  1. POST /entitlements/invites/validate  {"code": "..."}
  2. GET  /auth/google/start?...&invite=<normalized code>
     so the new account is stored with referred_by
  3. GET  /entitlements/me                plan, weekly usage, referral code

Every computer-use job then calls POST /entitlements/usage/check {"action": "cursor"}
before it runs. `cursor` is the weekly pool that counts those actions. Limits and
invite counts are whatever that response says. This module does not invent them.

Live contract checked against the Lightsail backend (image admeasy-entitlements):
  POST /entitlements/invites/validate
  GET  /entitlements/plans
  GET  /entitlements/me
  POST /entitlements/usage/check
  POST /entitlements/usage/consume   (the assistant records usage; the desktop checks)
and GET /auth/google/start accepts an `invite` query parameter.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import httpx

UPGRADE_URL = "https://admeasy.ai"
# Weekly pool that counts computer-use actions. The usage body has a single field, `action`.
COMPUTER_USE_ACTION = "cursor"
# Jobs that do not drive the computer. Status is a fact probe; sign-in waits for the person.
EXEMPT_KINDS = frozenset({"status", "signin"})

_FEATURE_ALIASES = {
    "local_machine": ("local_machine", "laptop", "desktop", "own_computer"),
    "virtual_machine": ("virtual_machine", "vm", "cloud_computer", "cloud_vm"),
    "claude": ("claude",),
    "vision": ("vision", "vision_model"),
    "deep_agents": ("deep_agents", "deep_agent"),
}
# Used only when /entitlements/me names a plan and does not send a feature map.
# Numeric limits are never filled in here.
_PLAN_FEATURES = {
    "free": {"local_machine": True, "virtual_machine": False, "claude": False, "vision": False, "deep_agents": False},
    "starter": {"local_machine": True, "virtual_machine": True, "claude": False, "vision": False, "deep_agents": False},
    "pro": {"local_machine": True, "virtual_machine": True, "claude": True, "vision": True, "deep_agents": True},
}
_PLAN_NAMES = {"free": "Free", "starter": "Starter", "pro": "Pro"}
_LIMIT_CODES = {"usage_limit", "limit", "quota", "rate_limited", "weekly_limit", "pool_exhausted", "cursor_limit"}


class EntitlementsError(Exception):
    """The entitlements API could not answer."""


class InviteError(EntitlementsError):
    def __init__(self, message: str, code: str = "invite_invalid"):
        super().__init__(message)
        self.code = code


class EntitlementsAuthError(EntitlementsError):
    """Access token missing or rejected."""


@dataclass
class InviteValidation:
    normalized_code: str
    kind: str
    raw: dict = field(default_factory=dict)


@dataclass
class UsageDecision:
    allowed: bool
    action: str
    code: str = "ok"
    message: str = ""
    remaining: int | None = None
    limit: int | None = None
    upgrade_url: str = UPGRADE_URL
    raw: dict = field(default_factory=dict)

    @property
    def is_limit(self) -> bool:
        if self.code in _LIMIT_CODES:
            return True
        return self.remaining == 0 and not self.allowed

    @classmethod
    def allow(cls, action: str = COMPUTER_USE_ACTION) -> "UsageDecision":
        return cls(allowed=True, action=action, code="ok")


@dataclass
class AccountEntitlements:
    invited: bool
    plan: str
    plan_family: str
    plan_name: str
    features: dict
    models: list
    usage: dict
    referral: dict | None
    referred_by_founder: bool
    raw: dict = field(default_factory=dict)

    def allows(self, feature: str) -> bool:
        return bool(self.features.get(feature))

    def public(self) -> dict:
        """Fields the local window may render. No tokens."""
        return {
            "invited": self.invited,
            "plan": self.plan,
            "plan_family": self.plan_family,
            "plan_name": self.plan_name,
            "features": dict(self.features),
            "models": list(self.models),
            "usage": dict(self.usage),
            "referral": dict(self.referral) if self.referral else None,
            "referred_by_founder": self.referred_by_founder,
            "upgrade_url": UPGRADE_URL,
        }

    @classmethod
    def allow_all(cls) -> "AccountEntitlements":
        """Test double: an invited Pro account. Production never uses this."""
        features = dict(_PLAN_FEATURES["pro"])
        return cls(
            invited=True,
            plan="pro",
            plan_family="pro",
            plan_name="Pro",
            features=features,
            models=models_for(features),
            usage={"remaining": None, "limit": None, "used": None, "period": "week", "resets_at": None},
            referral=None,
            referred_by_founder=False,
            raw={},
        )


def plan_family(plan: str) -> str:
    p = (plan or "").strip().lower()
    if p.startswith("pro") or p in ("paid", "enterprise"):
        return "pro"
    if p.startswith("starter"):
        return "starter"
    if p.startswith("free"):
        return "free"
    return p


def _as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "invited", "registered"):
            return True
        if v in ("0", "false", "no", "uninvited", "none"):
            return False
    return None


def _num(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _detail(data: dict | None, fallback: str) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict) and first.get("msg"):
                return str(first["msg"])
            if isinstance(first, str):
                return first
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def _invited(data: dict) -> bool:
    for key in ("invited", "is_invited", "registered", "is_registered"):
        if key in data and data.get(key) is not None:
            parsed = _as_bool(data.get(key))
            if parsed is not None:
                return parsed
    if data.get("referred_by_founder") is True:
        return True
    referred = data.get("referred_by")
    if isinstance(referred, str) and referred.strip():
        return True
    if isinstance(referred, dict) and (referred.get("id") or referred.get("code") or referred.get("label")):
        return True
    status = str(data.get("invite_status") or data.get("access") or "").strip().lower()
    if status in ("invited", "registered", "active"):
        return True
    if status in ("none", "required", "uninvited", "pending"):
        return False
    return False


def _plan_id(data: dict) -> str:
    for key in ("effective_plan", "plan", "plan_id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        if isinstance(value, dict):
            nested = value.get("id") or value.get("effective_plan") or value.get("plan")
            if isinstance(nested, str) and nested.strip():
                return nested.strip().lower()
    return ""


def _feature_map(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    found = {}
    for canon, aliases in _FEATURE_ALIASES.items():
        for alias in aliases:
            if alias in raw:
                parsed = _as_bool(raw.get(alias))
                if parsed is not None:
                    found[canon] = parsed
                    break
    return found or None


def _features(data: dict, family: str, invited: bool) -> dict:
    for key in ("features", "entitlements", "capabilities"):
        parsed = _feature_map(data.get(key))
        if parsed:
            out = {name: False for name in _FEATURE_ALIASES}
            out.update(parsed)
            if "local_machine" not in parsed and family in _PLAN_FEATURES:
                out["local_machine"] = _PLAN_FEATURES[family]["local_machine"]
            return out
    if family in _PLAN_FEATURES:
        return dict(_PLAN_FEATURES[family])
    # Invited, but the payload did not name a plan or a feature map. This computer
    # is the local-machine feature they were invited to. Claude and vision stay off
    # until the API says otherwise.
    if invited:
        return {"local_machine": True, "virtual_machine": False, "claude": False, "vision": False, "deep_agents": False}
    return {name: False for name in _FEATURE_ALIASES}


def models_for(features: dict, listed: list | None = None) -> list[str]:
    if listed:
        models = [str(m) for m in listed if str(m).strip()]
        if not features.get("claude"):
            models = [m for m in models if "claude" not in m.lower()]
        if not features.get("vision"):
            models = [m for m in models if "vision" not in m.lower()]
        return models
    models = ["sarvam", "groq"]
    if features.get("claude"):
        models.insert(0, "claude")
    if features.get("vision") and features.get("claude"):
        models.append("claude-vision")
    return models


def _usage(data: dict) -> dict:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    pools = data.get("pools") if isinstance(data.get("pools"), dict) else {}
    cursor = usage.get(COMPUTER_USE_ACTION) or pools.get(COMPUTER_USE_ACTION) or data.get(COMPUTER_USE_ACTION) or {}
    if not isinstance(cursor, dict):
        cursor = {}
    remaining = _num(cursor.get("remaining") if "remaining" in cursor else cursor.get("left"))
    limit = _num(cursor.get("limit") if "limit" in cursor else cursor.get("cap"))
    used = _num(cursor.get("used"))
    period = str(cursor.get("period") or cursor.get("window") or ("week" if cursor else ""))
    return {
        "remaining": remaining,
        "limit": limit,
        "used": used,
        "period": period,
        "resets_at": cursor.get("resets_at") or cursor.get("reset_at"),
    }


def _referral(data: dict) -> dict | None:
    ref = data.get("referral")
    if not isinstance(ref, dict):
        return None
    code = ref.get("code") or ref.get("referral_code")
    if not code:
        return None
    remaining = ref.get("remaining") if "remaining" in ref else ref.get("invites_remaining")
    cap = ref.get("cap") if "cap" in ref else ref.get("limit") if "limit" in ref else ref.get("invites_limit")
    return {"code": str(code), "remaining": _num(remaining), "cap": _num(cap)}


def parse_me(data: dict | None) -> AccountEntitlements:
    body = data if isinstance(data, dict) else {}
    user = body.get("user") if isinstance(body.get("user"), dict) else {}
    account = body.get("account") if isinstance(body.get("account"), dict) else {}
    merged = {**user, **account, **body}
    invited = _invited(merged)
    plan = _plan_id(merged)
    family = plan_family(plan)
    features = _features(merged, family, invited)
    listed = merged.get("models") or merged.get("allowed_models") or merged.get("llm_models")
    name = merged.get("plan_name") or merged.get("name")
    if not isinstance(name, str) or not name.strip() or name.strip().lower() == plan:
        name = _PLAN_NAMES.get(family) or (plan or "Free")
    return AccountEntitlements(
        invited=invited,
        plan=plan,
        plan_family=family,
        plan_name=str(name).strip(),
        features=features,
        models=models_for(features, listed if isinstance(listed, list) else None),
        usage=_usage(merged),
        referral=_referral(merged),
        referred_by_founder=bool(merged.get("referred_by_founder")),
        raw=body,
    )


def parse_usage(status: int, data: dict | None, action: str) -> UsageDecision:
    body = data if isinstance(data, dict) else {}
    if status == 401:
        raise EntitlementsAuthError(_detail(body, "sign in again"))
    usage = _usage(body)
    remaining = _num(body.get("remaining"))
    if remaining is None:
        remaining = usage["remaining"]
    limit = _num(body.get("limit"))
    if limit is None:
        limit = usage["limit"]
    upgrade = body.get("upgrade_url") if isinstance(body.get("upgrade_url"), str) else UPGRADE_URL
    if status in (402, 403, 429):
        return UsageDecision(
            allowed=False,
            action=str(body.get("action") or action),
            code=str(body.get("error") or body.get("reason") or "usage_limit"),
            message=_detail(body, "This week's computer actions are used up."),
            remaining=remaining,
            limit=limit,
            upgrade_url=upgrade,
            raw=body,
        )
    if status >= 400:
        return UsageDecision(
            allowed=False,
            action=action,
            code=str(body.get("error") or "error"),
            message=_detail(body, "Couldn't check this week's usage."),
            remaining=remaining,
            limit=limit,
            upgrade_url=upgrade,
            raw=body,
        )
    allowed = body.get("allowed")
    if allowed is None:
        allowed = body.get("ok")
    if allowed is None:
        allowed = not body.get("error")
    return UsageDecision(
        allowed=bool(allowed),
        action=str(body.get("action") or action),
        code=str(body.get("error") or body.get("reason") or ("ok" if allowed else "denied")),
        message=_detail(body, ""),
        remaining=remaining,
        limit=limit,
        upgrade_url=upgrade,
        raw=body,
    )


def feature_message(feature: str, snap: AccountEntitlements) -> str:
    name = snap.plan_name or "your plan"
    if feature == "claude":
        return f"Claude isn't included on {name}. Pro includes Claude, including vision. Upgrade at {UPGRADE_URL}."
    if feature == "vision":
        return f"The vision model isn't included on {name}. Upgrade at {UPGRADE_URL}."
    if feature == "virtual_machine":
        return f"The virtual machine isn't included on {name}. This plan can use your own computer. Upgrade at {UPGRADE_URL}."
    if feature == "deep_agents":
        return f"More deep agents aren't included on {name}. Upgrade at {UPGRADE_URL}."
    if feature == "local_machine":
        return f"This computer isn't included on {name}. Upgrade at {UPGRADE_URL}."
    return f"That isn't included on {name}. Upgrade at {UPGRADE_URL}."


def limit_message(decision: UsageDecision, snap: AccountEntitlements) -> str:
    url = decision.upgrade_url or UPGRADE_URL
    if decision.message:
        text = decision.message.strip().rstrip(".")
        if url not in text:
            text = f"{text}. Upgrade at {url}."
        elif not text.endswith("."):
            text = text + "."
        return text
    name = snap.plan_name or "your plan"
    left = ""
    if decision.remaining is not None:
        left = f" ({decision.remaining} left this week)"
    return f"You've used this week's computer actions on {name}{left}. Upgrade at {url}."


def required_features(kind: str, params: dict | None) -> set[str]:
    """Plan features this job needs beyond the weekly computer-use pool."""
    p = params or {}
    needed: set[str] = set()
    profile = str(p.get("profile") or "").lower()
    if kind == "cli" and profile == "claude":
        needed.add("claude")
    blob = " ".join(str(p.get(k) or "") for k in ("model", "provider", "llm", "vision_model")).lower()
    if "claude" in blob:
        needed.add("claude")
    if p.get("vision") is True or "vision" in blob:
        needed.add("vision")
    if p.get("deep_agent") or p.get("deep_agents"):
        needed.add("deep_agents")
    return needed


class EntitlementsClient:
    def __init__(self, backend: str, http: httpx.Client | None = None, cache_s: float = 20):
        self.backend = backend.rstrip("/")
        self.http = http or httpx.Client(timeout=20)
        self.cache_s = cache_s
        self._lock = threading.Lock()
        self._cached: AccountEntitlements | None = None
        self._cached_at = 0.0

    def _url(self, path: str) -> str:
        return self.backend + path

    def validate_invite(self, code: str) -> InviteValidation:
        raw = (code or "").strip()
        if not raw:
            raise InviteError("Enter an invite code.", "invite_required")
        try:
            response = self.http.post(self._url("/entitlements/invites/validate"), json={"code": raw})
        except httpx.HTTPError as exc:
            raise EntitlementsError("Couldn't reach Admeasy to check that invite code.") from exc
        try:
            body = response.json()
        except Exception:
            body = {}
        if response.status_code == 200 and isinstance(body, dict) and body.get("valid"):
            normalized = str(body.get("normalized_code") or raw).strip()
            return InviteValidation(normalized_code=normalized, kind=str(body.get("kind") or ""), raw=body)
        code_name = str(body.get("error") or "invite_invalid") if isinstance(body, dict) else "invite_invalid"
        fallback = "Enter an invite code." if response.status_code == 400 else "That invite code isn't valid."
        raise InviteError(_detail(body if isinstance(body, dict) else None, fallback), code_name)

    def _bearer(self) -> str:
        from .auth import load_secret, refresh

        token = load_secret("access_token")
        if token:
            return token
        refreshed = refresh(self.backend)
        if refreshed:
            return refreshed
        raise EntitlementsAuthError("sign in required")

    def _authed(self, method: str, path: str, json_body: dict | None = None) -> httpx.Response:
        from .auth import refresh

        token = self._bearer()
        for attempt in range(2):
            try:
                response = self.http.request(
                    method,
                    self._url(path),
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise EntitlementsError("Couldn't reach Admeasy.") from exc
            if response.status_code == 401 and attempt == 0:
                refreshed = refresh(self.backend)
                if refreshed:
                    token = refreshed
                    continue
                raise EntitlementsAuthError("sign in again")
            return response
        raise EntitlementsAuthError("sign in again")

    def me(self, *, fresh: bool = False) -> AccountEntitlements:
        now = time.monotonic()
        with self._lock:
            if not fresh and self._cached and (now - self._cached_at) < self.cache_s:
                return self._cached
        response = self._authed("GET", "/entitlements/me")
        try:
            body = response.json()
        except Exception:
            body = {}
        if response.status_code == 401:
            raise EntitlementsAuthError(_detail(body if isinstance(body, dict) else None, "sign in again"))
        if response.status_code != 200 or not isinstance(body, dict):
            raise EntitlementsError(_detail(body if isinstance(body, dict) else None, "Couldn't load your plan."))
        snap = parse_me(body)
        with self._lock:
            self._cached = snap
            self._cached_at = time.monotonic()
        return snap

    def usage_check(self, action: str = COMPUTER_USE_ACTION) -> UsageDecision:
        response = self._authed("POST", "/entitlements/usage/check", {"action": action})
        try:
            body = response.json()
        except Exception:
            body = {}
        return parse_usage(response.status_code, body if isinstance(body, dict) else {}, action)

    def plans(self) -> list[dict]:
        try:
            response = self.http.get(self._url("/entitlements/plans"))
        except httpx.HTTPError as exc:
            raise EntitlementsError("Couldn't load plans.") from exc
        if response.status_code != 200:
            return []
        body = response.json()
        plans = body.get("plans") if isinstance(body, dict) else None
        return list(plans) if isinstance(plans, list) else []
