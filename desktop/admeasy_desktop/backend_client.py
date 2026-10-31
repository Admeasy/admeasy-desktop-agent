"""Authenticated REST calls to the shared Lightsail backend (same contract as the phone app)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from . import auth
from .config import Settings

log = logging.getLogger("admeasy-desktop")


class BackendError(Exception):
    def __init__(self, message: str, status: int = 0, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class BackendClient:
    def __init__(self, settings: Settings):
        self.base = settings.backend.rstrip("/")
        self.settings = settings

    def _token(self) -> str | None:
        tok = auth.load_secret("access_token")
        if tok:
            return tok
        try:
            return auth.refresh(self.base)
        except Exception:
            return None

    def headers(self) -> dict[str, str]:
        tok = self._token()
        if not tok:
            raise BackendError("sign in first", 401)
        return {"Authorization": f"Bearer {tok}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
        params: dict | None = None,
        timeout: float = 5,
        auth_required: bool = True,
    ) -> Any:
        url = f"{self.base}{path if path.startswith('/') else '/' + path}"
        hdrs = self.headers() if auth_required else {}
        try:
            r = httpx.request(method, url, headers=hdrs, json=json_body, params=params, timeout=timeout)
        except httpx.HTTPError as exc:
            raise BackendError(f"could not reach the backend: {exc}") from exc
        if auth_required and r.status_code == 401:
            if auth.refresh(self.base):
                hdrs = self.headers()
                r = httpx.request(method, url, headers=hdrs, json=json_body, params=params, timeout=timeout)
        if r.status_code >= 400:
            detail = None
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:400]
            raise BackendError(f"{path} returned {r.status_code}", r.status_code, detail)
        if not r.content:
            return {}
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}
