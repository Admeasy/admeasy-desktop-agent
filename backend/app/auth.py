"""Google Sign-In and email/password sign-in → JWT.

Access tokens are short-lived HS256 JWTs; refresh tokens are opaque and stored hashed.
Password sign-in checks Supabase Auth with the anon/publishable key, then issues the same
app tokens as Google. Passwords, Supabase sessions, and app tokens are never logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

log = logging.getLogger("admeasy.auth")

GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"
ACCESS_TTL_S = 60 * 60 * 12  # 12h
REFRESH_TTL_S = 60 * 60 * 24 * 30  # 30d

api = APIRouter(prefix="/auth")
bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthedUser:
    id: str
    email: str
    preferred_llm: str


class GoogleBody(BaseModel):
    id_token: str | None = None
    access_token: str | None = None  # Android may send an access token from GoogleSignIn


class PrefsBody(BaseModel):
    preferred_llm: str | None = None  # sarvam | claude (legacy: groq)


async def _google_profile(id_token: str | None, access_token: str | None) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        if id_token:
            r = await c.get(GOOGLE_TOKENINFO, params={"id_token": id_token})
            if r.status_code >= 400:
                raise HTTPException(401, "invalid Google id_token")
            p = r.json()
            return {"sub": p["sub"], "email": p.get("email"), "name": p.get("name"), "picture": p.get("picture")}
        if access_token:
            r = await c.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code >= 400:
                raise HTTPException(401, "invalid Google access_token")
            p = r.json()
            return {"sub": p["sub"], "email": p.get("email"), "name": p.get("name"), "picture": p.get("picture")}
    raise HTTPException(400, "id_token or access_token required")


def _issue(user_id: str, email: str, secret: str) -> dict:
    now = int(time.time())
    access = jwt.encode({"sub": user_id, "email": email, "iat": now, "exp": now + ACCESS_TTL_S}, secret, algorithm="HS256")
    refresh = secrets.token_urlsafe(48)
    return {"access_token": access, "refresh_token": refresh, "expires_in": ACCESS_TTL_S}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Same row shape for Google and password sign-in. Password accounts store the
# Supabase auth user id in google_sub (the stable identity, like Google's sub).
USER_UPSERT_SQL = """INSERT INTO users (google_sub, email, name, picture_url, last_seen_at)
   VALUES ($1,$2,$3,$4, now())
   ON CONFLICT (google_sub) DO UPDATE SET email=EXCLUDED.email, name=EXCLUDED.name,
     picture_url=EXCLUDED.picture_url, last_seen_at=now()
   RETURNING id::text, email, preferred_llm"""
SESSION_INSERT_SQL = """INSERT INTO sessions (user_id, refresh_hash, expires_at)
   VALUES ($1::uuid, $2, now() + make_interval(secs => $3))"""

# In-process limits. Enough for a person, tight for a password guesser.
PASSWORD_LIMIT_EMAIL = 10
PASSWORD_LIMIT_IP = 30
PASSWORD_WINDOW_S = 15 * 60
PASSWORD_BODY_MAX = 4096


class _SlidingWindow:
    def __init__(self) -> None:
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str, *, limit: int, window_s: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        recent = [t for t in self.hits.get(key, []) if now - t < window_s]
        if len(recent) >= limit:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        if len(self.hits) > 4096:
            cutoff = now - window_s
            self.hits = {k: v for k, v in self.hits.items() if v and v[-1] >= cutoff}
        return True


password_attempts = _SlidingWindow()


def reset_password_rate_limit() -> None:
    password_attempts.hits.clear()


def supabase_auth_key(settings) -> str:
    """Anon or publishable key for the Supabase password grant. Never the service role key."""
    publishable = str(getattr(settings, "supabase_publishable_key", "") or "").strip()
    anon = str(getattr(settings, "supabase_anon_key", "") or "").strip()
    return publishable or anon


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]
    client = request.client
    return client.host if client else "unknown"


async def _establish_session(conn, profile: dict, secret: str):
    row = await conn.fetchrow(
        USER_UPSERT_SQL,
        profile["sub"], profile["email"], profile.get("name"), profile.get("picture"))
    tok = _issue(row["id"], row["email"], secret)
    await conn.execute(SESSION_INSERT_SQL, row["id"], _hash(tok["refresh_token"]), REFRESH_TTL_S)
    return row, tok


def _auth_response(row, tok: dict, profile: dict) -> dict:
    return {**tok, "user": {"id": row["id"], "email": row["email"], "preferred_llm": row["preferred_llm"],
                            "name": profile.get("name"), "picture": profile.get("picture")}}


async def _supabase_password_profile(url: str, api_key: str, email: str, password: str) -> dict:
    """Password grant. The Supabase access and refresh tokens are discarded here and never logged."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{url}/auth/v1/token",
                params={"grant_type": "password"},
                headers={
                    "apikey": api_key,
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"email": email, "password": password},
            )
    except httpx.HTTPError:
        log.warning("password sign-in upstream unreachable")
        raise HTTPException(503, "password sign-in unavailable")
    if response.status_code != 200:
        log.info("password sign-in rejected status=%s", response.status_code)
        raise HTTPException(401, "invalid email or password")
    try:
        payload = response.json()
    except ValueError:
        log.info("password sign-in rejected status=%s", response.status_code)
        raise HTTPException(401, "invalid email or password")
    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict) or not user.get("id") or not user.get("email"):
        log.info("password sign-in rejected status=%s", response.status_code)
        raise HTTPException(401, "invalid email or password")
    meta = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    return {
        "sub": str(user["id"]),
        "email": user["email"],
        "name": meta.get("name") or meta.get("full_name"),
        "picture": meta.get("picture") or meta.get("avatar_url"),
    }


@api.get("/google/start")
async def google_browser_start(request: Request, desktop_port: int | None = None, nonce: str = ""):
    """Browser Google Sign-In for the app: opens Google, then deep-links back with JWTs (no Android SHA-1 needed)."""
    from app.oauth_providers import build_providers
    s = request.app.state.settings
    if not s.jwt_secret or not s.google_client_id:
        raise HTTPException(503, "Google Sign-In not configured")
    p = build_providers(s)["google"]
    # Override scopes and redirect for sign-in (identity only).
    p.scopes = "openid email profile"
    # Same redirect URI as "Connect Google" (already registered in Google Cloud); state marks this as sign-in.
    p.extra_auth_params = {"access_type": "online", "prompt": "select_account"}
    verifier, challenge = p.pkce_pair()
    from cryptography.fernet import Fernet
    # Reuse token vault's Fernet when available; else a dedicated short-lived state using jwt_secret is fine.
    vault = getattr(request.app.state, "vault", None)
    if vault is None:
        raise HTTPException(503, "token vault required for sign-in state")
    state = vault.f.encrypt(json.dumps({"v": verifier, "t": time.time(), "k": "signin", "p": "google",
                                                   "dp": desktop_port if desktop_port and 1024 <= desktop_port <= 65535 else None,
                                                   "n": nonce[:64]}).encode()).decode()
    return RedirectResponse(p.authorize_url(state, challenge), status_code=302)


async def finish_google_signin(request: Request, code: str, st: dict):
    """Called from /oauth/google/callback when the state is a sign-in state."""
    from fastapi.responses import HTMLResponse
    s = request.app.state.settings
    from app.oauth_providers import build_providers
    p = build_providers(s)["google"]
    tok = await p.exchange(code, st["v"])
    profile = await _google_profile(None, tok["access_token"])
    async with request.app.state.pool.acquire() as c:
        _row, issued = await _establish_session(c, profile, s.jwt_secret)
    deep = (f"admeasy://auth?access_token={issued['access_token']}&refresh_token={issued['refresh_token']}"
            f"&email={profile['email']}")
    if st.get("dp"):  # desktop app: hand the tokens to its loopback listener, never to a remote host
        from urllib.parse import urlencode
        deep = f"http://127.0.0.1:{int(st['dp'])}/callback?" + urlencode(
            {"access_token": issued["access_token"], "refresh_token": issued["refresh_token"],
             "email": profile["email"], "nonce": st.get("n") or ""})
    return HTMLResponse(f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
      <p>Signed in as {profile.get('email')}. Returning to Admeasy…</p>
      <script>location.href={json.dumps(deep)};</script>
      <a href="{deep}">Open Admeasy</a>""")


@api.post("/google")
async def google_sign_in(body: GoogleBody, request: Request):
    s = request.app.state.settings
    if not s.jwt_secret:
        raise HTTPException(503, "JWT_SECRET not configured")
    profile = await _google_profile(body.id_token, body.access_token)
    if not profile.get("email"):
        raise HTTPException(400, "Google account has no email")
    # Optional audience check when we have a client id configured
    async with request.app.state.pool.acquire() as c:
        row, tok = await _establish_session(c, profile, s.jwt_secret)
    return _auth_response(row, tok, profile)


@api.post("/password")
async def password_sign_in(request: Request):
    """Email and password → the same access and refresh tokens as POST /auth/google.

    Credentials are checked with Supabase's password grant and the anon/publishable key.
    The matching public.users row is upserted on the Supabase auth user id. The password,
    the Supabase session, and the tokens issued here are not written to logs.
    """
    raw = await request.body()
    if len(raw) > PASSWORD_BODY_MAX:
        raise HTTPException(400, "email and password required")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "email and password required")
    if not isinstance(payload, dict):
        raise HTTPException(400, "email and password required")
    email_raw = payload.get("email")
    password = payload.get("password")
    email = email_raw.strip().lower() if isinstance(email_raw, str) else ""
    if not isinstance(password, str) or not email or "@" not in email or not password:
        raise HTTPException(400, "email and password required")
    if len(email) > 320 or len(password) > 1024:
        raise HTTPException(400, "email and password required")
    s = request.app.state.settings
    url = str(getattr(s, "supabase_url", "") or "").strip().rstrip("/")
    api_key = supabase_auth_key(s)
    if not getattr(s, "jwt_secret", "") or not url or not api_key:
        raise HTTPException(503, "password sign-in not configured")
    ip = _client_ip(request)
    if not password_attempts.allow(f"ip:{ip}", limit=PASSWORD_LIMIT_IP, window_s=PASSWORD_WINDOW_S):
        raise HTTPException(429, "too many attempts")
    if not password_attempts.allow(f"email:{email}", limit=PASSWORD_LIMIT_EMAIL, window_s=PASSWORD_WINDOW_S):
        raise HTTPException(429, "too many attempts")
    profile = await _supabase_password_profile(url, api_key, email, password)
    async with request.app.state.pool.acquire() as c:
        row, tok = await _establish_session(c, profile, s.jwt_secret)
    return _auth_response(row, tok, profile)


class RefreshBody(BaseModel):
    refresh_token: str


@api.post("/refresh")
async def refresh(body: RefreshBody, request: Request):
    s = request.app.state.settings
    h = _hash(body.refresh_token)
    async with request.app.state.pool.acquire() as c:
        row = await c.fetchrow(
            """SELECT s.id, u.id::text AS uid, u.email FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.refresh_hash=$1 AND s.revoked_at IS NULL AND s.expires_at > now()""", h)
        if not row:
            raise HTTPException(401, "invalid refresh token")
        tok = _issue(row["uid"], row["email"], s.jwt_secret)
        await c.execute("UPDATE sessions SET refresh_hash=$1, expires_at=now()+make_interval(secs=>$2) WHERE id=$3",
                        _hash(tok["refresh_token"]), REFRESH_TTL_S, row["id"])
    return tok


async def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AuthedUser:
    s = request.app.state.settings
    if not creds or not s.jwt_secret:
        raise HTTPException(401, "Bearer token required")
    try:
        payload = jwt.decode(creds.credentials, s.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    from app.voice.listen import lookup_prefs
    prefs = await lookup_prefs(request.app.state.pool, payload["sub"], getattr(request.app.state, "row_cache", None))
    if prefs.get("email") or prefs.get("preferred_llm"):
        return AuthedUser(prefs["id"], prefs.get("email") or "", prefs.get("preferred_llm"))
    # No cached identity (missing row, or both fields empty). One indexed read confirms the user.
    async with request.app.state.pool.acquire() as c:
        row = await c.fetchrow("SELECT id::text, email, preferred_llm FROM users WHERE id=$1::uuid", payload["sub"])
    if not row:
        raise HTTPException(401, "user not found")
    return AuthedUser(row["id"], row["email"] or "", row["preferred_llm"])


@api.get("/me")
async def me(request: Request, user: AuthedUser = Depends(current_user)):
    from app.voice.listen import lookup_prefs
    prefs = await lookup_prefs(request.app.state.pool, user.id, getattr(request.app.state, "row_cache", None))
    connected = await request.app.state.vault.connected(user.id) if request.app.state.vault else []
    plan = prefs.get("plan") or "free"
    from app.llm_policy import claude_allowed, groq_allowed
    pref = prefs.get("preferred_llm") or "sarvam"
    if pref == "groq":
        pref = "claude"
    if pref == "claude" and not claude_allowed(plan):
        pref = "sarvam"
    unlocked = claude_allowed(plan)
    return {"user": {"id": prefs["id"], "email": prefs.get("email"), "name": prefs.get("name"),
                     "picture_url": prefs.get("picture_url"), "preferred_llm": pref, "plan": plan,
                     "claude_unlocked": unlocked, "groq_unlocked": unlocked},
            "connected": connected}


@api.patch("/me")
async def update_me(body: PrefsBody, request: Request, user: AuthedUser = Depends(current_user)):
    if body.preferred_llm and body.preferred_llm not in ("sarvam", "claude", "groq"):
        raise HTTPException(400, "preferred_llm must be sarvam or claude")
    store_llm = body.preferred_llm
    if store_llm == "groq":
        store_llm = "claude"
    if store_llm == "claude":
        from app.voice.listen import lookup_prefs
        from app.llm_policy import claude_allowed
        prefs = await lookup_prefs(request.app.state.pool, user.id, getattr(request.app.state, "row_cache", None))
        if not claude_allowed(prefs.get("plan")):
            raise HTTPException(403, "Claude is available on Pro. Upgrade or use Sarvam.")
    async with request.app.state.pool.acquire() as c:
        if store_llm:
            await c.execute("UPDATE users SET preferred_llm=$1 WHERE id=$2::uuid", store_llm, user.id)
        row = await c.fetchrow("SELECT id::text, email, preferred_llm FROM users WHERE id=$1::uuid", user.id)
    cache = getattr(request.app.state, "row_cache", None)
    if cache is not None:
        cache.drop(("user", user.id))
        cache.drop(("plan", user.id))
    return {"user": dict(row)}


def decode_user_id(token: str | None, secret: str) -> str | None:
    if not token or not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None


async def identity(request: Request, token: str | None = None, user_id: str | None = None) -> str:
    """Authed user id from 'Authorization: Bearer <jwt>' or ?token=<jwt> (browser redirects, WebSocket).
    Legacy ?user_id= is accepted only while ALLOW_LEGACY_USER_ID=true (old APKs during the migration)."""
    s = getattr(request.app.state, "settings", None)
    auth = request.headers.get("authorization", "")
    tok = auth[7:].strip() if auth.lower().startswith("bearer ") else token
    uid = decode_user_id(tok, getattr(s, "jwt_secret", ""))
    if uid:
        return uid
    if getattr(s, "allow_legacy_user_id", True) and user_id:
        return user_id
    raise HTTPException(401, "sign in required")
