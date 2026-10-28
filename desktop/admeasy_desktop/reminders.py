"""Local reminders, with a best-effort sync to the shared backend.

The scheduler that should own reminders lives on Lightsail. Until that route
exists, the helper stores them and delivers a native toast (and a window event)
when they are due. Delivery to WhatsApp needs the backend change listed in the PR.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from . import config
from .config import Settings
from .notify import toast

_LOCK = threading.Lock()


def _path():
    return config.HOME / "reminders.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(rows: list[dict]) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(rows, indent=2))


def list_reminders() -> list[dict]:
    with _LOCK:
        return _load()


def add_reminder(settings: Settings, text: str, at_iso: str, access_token: str | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("write what to be reminded about")
    when = _parse(at_iso)
    row = {
        "id": uuid.uuid4().hex,
        "text": text[:400],
        "at": when.astimezone(timezone.utc).isoformat(),
        "status": "scheduled",
        "remote": "local",
    }
    with _LOCK:
        rows = _load()
        rows.append(row)
        _save(rows)
    remote = _push_remote(settings, row, access_token)
    if remote:
        row["remote"] = remote
        with _LOCK:
            rows = _load()
            for i, item in enumerate(rows):
                if item.get("id") == row["id"]:
                    rows[i] = row
            _save(rows)
    return row


def cancel_reminder(reminder_id: str, settings: Settings | None = None, access_token: str | None = None) -> None:
    with _LOCK:
        rows = [r for r in _load() if r.get("id") != reminder_id]
        _save(rows)
    if settings and access_token:
        try:
            httpx.delete(
                f"{settings.backend.rstrip('/')}/reminders/{reminder_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=8,
            )
        except Exception:
            pass


def deliver_due(now: datetime | None = None, notify: bool = True) -> list[dict]:
    moment = now or datetime.now(timezone.utc)
    delivered = []
    with _LOCK:
        rows = _load()
        changed = False
        for row in rows:
            if row.get("status") != "scheduled":
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
            _save(rows)
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


def _push_remote(settings: Settings, row: dict, access_token: str | None) -> str:
    if not access_token:
        return "local"
    try:
        r = httpx.post(
            f"{settings.backend.rstrip('/')}/reminders",
            json={"text": row["text"], "at": row["at"], "client": "desktop", "id": row["id"]},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=8,
        )
    except Exception:
        return "local"
    if r.status_code == 404:
        return "unsupported"
    if r.status_code < 300:
        return "saved"
    return "local"


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
