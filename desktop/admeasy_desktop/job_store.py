"""Idempotency keys and buffered results for tunnel reconnect."""
from __future__ import annotations

import json
import threading
from pathlib import Path

STORE = Path.home() / ".admeasy" / "job_store.json"
MAX_IDEMPOTENT = 200


def _slim(payload: dict) -> dict:
    """Screenshots are not kept for replays; the result facts are."""
    body = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(body, dict) and "screenshot_b64" in body:
        return {**payload, "result": {k: v for k, v in body.items() if k != "screenshot_b64"}}
    return payload


class JobStore:
    def __init__(self, path: Path | None = None):
        self.path = path or STORE
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"idempotent": {}, "pending_results": []}
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {"idempotent": {}, "pending_results": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data))

    def get_idempotent(self, key: str) -> dict | None:
        if not key:
            return None
        with self._lock:
            return self._data.get("idempotent", {}).get(key)

    def put_idempotent(self, key: str, payload: dict) -> None:
        if not key:
            return
        with self._lock:
            idem = self._data.setdefault("idempotent", {})
            idem.pop(key, None)
            idem[key] = _slim(payload)
            for old in list(idem)[:-MAX_IDEMPOTENT]:  # every job now has a key: keep the newest only
                idem.pop(old, None)
            self._save()

    def buffer_result(self, msg: dict) -> None:
        with self._lock:
            self._data.setdefault("pending_results", []).append(msg)
            self._save()

    def pop_pending(self) -> list[dict]:
        with self._lock:
            pending = list(self._data.get("pending_results") or [])
            self._data["pending_results"] = []
            self._save()
            return pending
