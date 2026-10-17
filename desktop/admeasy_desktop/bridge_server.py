"""Local socket bridge: desktop agent <-> native messaging host <-> Chromium extension."""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from pathlib import Path

log = logging.getLogger("admeasy-bridge")

BRIDGE_ROOT = Path.home() / ".admeasy" / "bridge"
ADDR_FILE = BRIDGE_ROOT / "agent_addr.json"
_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()
_clients: list[socket.socket] = []
_clients_lock = threading.Lock()
_server: socket.socket | None = None
_thread: threading.Thread | None = None


def _addr_path() -> tuple[str, int | str]:
    if ADDR_FILE.is_file():
        try:
            meta = json.loads(ADDR_FILE.read_text())
            if meta.get("family") == "unix":
                return "unix", meta["path"]
            return meta.get("host", "127.0.0.1"), int(meta["port"])
        except Exception:
            pass
    return "127.0.0.1", 0


def start() -> None:
    global _server, _thread
    if _thread and _thread.is_alive() and _server is not None:
        return
    BRIDGE_ROOT.mkdir(parents=True, exist_ok=True)
    import sys

    if sys.platform == "win32":
        _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _server.bind(("127.0.0.1", 0))
        host, port = _server.getsockname()[:2]
        ADDR_FILE.write_text(json.dumps({"family": "tcp", "host": host, "port": port}))
    else:
        sock_path = BRIDGE_ROOT / "agent.sock"
        sock_path.unlink(missing_ok=True)
        _server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        _server.bind(str(sock_path))
        ADDR_FILE.write_text(json.dumps({"family": "unix", "path": str(sock_path)}))
    _server.listen(8)
    _server.settimeout(1.0)

    def serve() -> None:
        while _server:
            try:
                conn, _ = _server.accept()
                conn.settimeout(0.5)
                with _clients_lock:
                    _clients.append(conn)
                threading.Thread(target=_client_loop, args=(conn,), daemon=True).start()
            except OSError:
                continue

    _thread = threading.Thread(target=serve, daemon=True, name="admeasy-bridge-server")
    _thread.start()
    log.info("bridge server listening (%s)", ADDR_FILE)


def stop() -> None:
    global _server
    if _server:
        try:
            _server.close()
        except OSError:
            pass
        _server = None


def _client_loop(conn: socket.socket) -> None:
    buf = b""
    try:
        while True:
            try:
                chunk = conn.recv(65536)
            except socket.timeout:
                continue
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
                if msg.get("type") == "response" and msg.get("id"):
                    with _pending_lock:
                        _pending[msg["id"]] = msg
                elif msg.get("type") == "ready":
                    pass
    finally:
        with _clients_lock:
            if conn in _clients:
                _clients.remove(conn)
        conn.close()


def _broadcast(line: bytes) -> bool:
    with _clients_lock:
        clients = list(_clients)
    if not clients:
        return False
    ok = False
    for c in clients:
        try:
            c.sendall(line)
            ok = True
        except OSError:
            with _clients_lock:
                if c in _clients:
                    _clients.remove(c)
    return ok


def request_socket(op: str, params: dict, timeout_s: float = 45.0) -> dict | None:
    import uuid

    rid = str(uuid.uuid4())
    payload = json.dumps({"type": "request", "id": rid, "op": op, "params": params}).encode() + b"\n"
    if not _broadcast(payload):
        return None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with _pending_lock:
            hit = _pending.pop(rid, None)
        if hit is not None:
            return {k: v for k, v in hit.items() if k not in ("type", "id")}
        time.sleep(0.02)
    return {"status": "timeout", "reason": "extension_not_connected"}


def client_count() -> int:
    with _clients_lock:
        return len(_clients)
