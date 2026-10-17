"""In-memory log ring for the local UI (and optional file mirror)."""
from __future__ import annotations

import logging
from collections import deque
from threading import Lock

_MAX_LINES = 400
_buf: deque[str] = deque(maxlen=_MAX_LINES)
_lock = Lock()


class UiLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        with _lock:
            _buf.append(line)


def tail(n: int = 120) -> list[str]:
    with _lock:
        return list(_buf)[-n:]


def configure_logging(log_file: str | None = None, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%H:%M:%S")
    ui = UiLogHandler()
    ui.setFormatter(fmt)
    root.addHandler(ui)
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(fh)
