#!/usr/bin/env python3
"""Chrome native messaging host: forwards extension messages to ~/.admeasy/bridge."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path.home() / ".admeasy" / "bridge"
INBOX = ROOT / "inbox"
OUTBOX = ROOT / "outbox"


def read_msg() -> dict | None:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        return None
    length = struct.unpack("<I", raw_len)[0]
    data = sys.stdin.buffer.read(length)
    return json.loads(data.decode("utf-8"))


def write_msg(obj: dict) -> None:
    payload = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    while True:
        msg = read_msg()
        if msg is None:
            break
        rid = msg.get("id") or msg.get("request_id")
        if rid:
            (INBOX / f"{rid}.json").write_text(json.dumps(msg))
        # Poll outbox briefly (extension worker fills via separate channel in full build)
        out = OUTBOX / f"{rid}.json"
        if out.is_file():
            write_msg(json.loads(out.read_text()))
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
