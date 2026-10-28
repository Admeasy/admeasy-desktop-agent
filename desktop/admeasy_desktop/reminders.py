"""Reminders via the shared backend, with local fallback when offline."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

import httpx

from . import config
from .config import Settings
from .notify import toast

_LOCK = threading.Lock()


def _path():
    return config.HOME / "reminders.json"


def _load_local() -> list[dict]:
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_local(rows: list[dict]) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(rows, indent=2))


def _items(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("reminders", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize(row: dict) -> dict:
    status = str(row.get("status") or "scheduled")
    rid = str(row.get("id") or row.get("reminder_id") or uuid.uuid4().hex)
    at = row.get("at") or row.get("scheduled_at") or row.get("fire_at") or ""
    return {
        "id": rid,
        "text": str(row.get("text") or row.get("body") or "")[:400],
        "at": str(at),
        "status": status,
        "remote": "backend",
    }


def _fetch_remote(settings: Settings, access_token: str | None) -> list[dict]:
    if not access_token:
        return []
    try:
        r = httpx.get(
            f"{settings.backend.rstrip('/')}/reminders",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": 50},
            timeout=12,
        )
    except Exception:
        return []
    if r.status_code == 401:
        from . import auth
        fresh = auth.refresh(settings.backend)
        if fresh:
            return _fetch_remote(settings, fresh)
        return []
    if r.status_code >= 300:
        return []
    return [_normalize(row) for row in _items(r.json()) if isinstance(row, dict)]


def list_reminders(settings: Settings | None = None, access_token: str | None = None) -> list[dict]:
    remote = _fetch_remote(settings, access_token) if settings else []
    if remote:
        return sorted(remote, key=lambda r: r.get("at") or "")
    with _LOCK:
        return _load_local()


def add_reminder(settings: Settings, text: str, at_iso: str, access_token: str | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("write what to be reminded about")
    when = _parse(at_iso)
    at_utc = when.astimezone(timezone.utc).isoformat()
    if access_token:
        try:
            r = httpx.post(
                f"{settings.backend.rstrip('/')}/reminders",
                json={"text": text[:400], "at": at_utc, "client": "desktop"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=12,
            )
        except Exception:
            r = None
        if r is not None and r.status_code == 401:
            from . import auth
            access_token = auth.refresh(settings.backend) or access_token
            r = httpx.post(
                f"{settings.backend.rstrip('/')}/reminders",
                json={"text": text[:400], "at": at_utc, "client": "desktop"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=12,
            )
        if r is not None and r.status_code < 300:
            body = r.json() if r.content else {}
            row = _normalize({**body, "text": text, "at": at_utc, "status": "scheduled"})
            return row
    row = {
        "id": uuid.uuid4().hex,
        "text": text[:400],
        "at": at_utc,
        "status": "scheduled",
        "remote": "local",
    }
    with _LOCK:
        rows = _load_local()
        rows.append(row)
        _save_local(rows)
    return row


def cancel_reminder(reminder_id: str, settings: Settings | None = None, access_token: str | None = None) -> None:
    if settings and access_token:
        try:
            r = httpx.delete(
                f"{settings.backend.rstrip('/')}/reminders/{reminder_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=12,
            )
        except Exception:
            r = None
        if r is not None and r.status_code == 401:
            from . import auth
            access_token = auth.refresh(settings.backend) or access_token
            httpx.delete(
                f"{settings.backend.rstrip('/')}/reminders/{reminder_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=12,
            )
        if r is not None and r.status_code < 300:
            return
    with _LOCK:
        rows = [r for r in _load_local() if r.get("id") != reminder_id]
        _save_local(rows)


def deliver_due(now: datetime | None = None, notify: bool = True) -> list[dict]:
    """Local-only delivery for reminders stored offline."""
    moment = now or datetime.now(timezone.utc)
    delivered = []
    with _LOCK:
        rows = _load_local()
        changed = False
        for row in rows:
            if row.get("status") != "scheduled" or row.get("remote") == "backend":
                continue
            try:
                when = _parse(row.get("at") or "")
            except ValueError:
                continue
            if when <= moment:
                row["status"] = "delivered"
                row["delivered_at"] = moment.astimezone(timezone.utc).isoformat()
                delivered.append(dict(row))
                changed = True
        if changed:
            _save_local(rows)
    if notify:
        for row in delivered:
            toast("Admeasy", row.get("text") or "reminder")
    return delivered


def _parse(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("pick a time")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


class Scheduler:
    def __init__(self, on_deliver=None):
        self.on_deliver = on_deliver
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="admeasy-reminders", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(5):
            try:
                rows = deliver_due(notify=True)
            except Exception:
                continue
            if rows and self.on_deliver:
                for row in rows:
                    try:
                        self.on_deliver(row)
                    except Exception:
                        pass
