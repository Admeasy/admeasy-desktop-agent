#!/usr/bin/env python3
"""Chrome native messaging host: duplex relay between browser and Admeasy bridge socket."""
from __future__ import annotations

import json
import socket
import struct
import sys
import threading
from pathlib import Path

ROOT = Path.home() / ".admeasy" / "bridge"
ADDR_FILE = ROOT / "agent_addr.json"


def read_chrome() -> dict | None:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len or len(raw_len) < 4:
        return None
    length = struct.unpack("<I", raw_len)[0]
    if length > 10_000_000:
        return None
    data = sys.stdin.buffer.read(length)
    return json.loads(data.decode("utf-8"))


def write_chrome(obj: dict) -> None:
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def connect_agent() -> socket.socket | None:
    if not ADDR_FILE.is_file():
        return None
    try:
        meta = json.loads(ADDR_FILE.read_text())
    except Exception:
        return None
    try:
        if meta.get("family") == "unix":
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(meta["path"])
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((meta.get("host", "127.0.0.1"), int(meta["port"])))
        s.sendall(b'{"type":"ready","role":"native_host"}\n')
        return s
    except OSError:
        return None


def main() -> None:
    agent = connect_agent()
    agent_lock = threading.Lock()
    stop = threading.Event()

    def agent_reader() -> None:
        if not agent:
            return
        buf = b""
        while not stop.is_set():
            try:
                chunk = agent.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode())
                except ValueError:
                    continue
                if msg.get("type") == "request":
                    write_chrome(msg)

    if agent:
        threading.Thread(target=agent_reader, daemon=True).start()

    while True:
        msg = read_chrome()
        if msg is None:
            break
        if agent:
            out = {"type": "response", **msg}
            with agent_lock:
                try:
                    agent.sendall((json.dumps(out, separators=(",", ":")) + "\n").encode())
                except OSError:
                    break
        else:
            # Legacy file fallback when agent socket unavailable
            rid = msg.get("id")
            if rid:
                (ROOT / "outbox" / f"{rid}.json").parent.mkdir(parents=True, exist_ok=True)
                (ROOT / "outbox" / f"{rid}.json").write_text(json.dumps(msg))


if __name__ == "__main__":
    main()
