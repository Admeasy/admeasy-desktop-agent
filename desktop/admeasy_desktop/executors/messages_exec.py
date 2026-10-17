"""macOS Messages / SMS (chat.db) and Windows stubs."""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime

from .. import permissions


def _chat_db() -> str:
    return os.path.expanduser("~/Library/Messages/chat.db")


def run(p: dict) -> dict:
    op = p.get("op") or "recent"
    if sys.platform != "darwin":
        if op == "send":
            return {"status": "failed", "error": "SMS send is only supported on macOS via Messages"}
        return {"status": "done", "result": {"messages": [], "platform": sys.platform, "note": "use phone link / Your Phone on Windows"}}

    if not permissions.can_read_full_disk():
        return {
            "status": "needs_permission",
            "error": "grant Full Disk Access to Admeasy (System Settings > Privacy & Security) to read Messages",
        }

    db = _chat_db()
    if not os.path.exists(db):
        return {"status": "failed", "error": "Messages database not found"}

    limit = min(int(p.get("limit") or 30), 200)
    handle = str(p.get("handle") or p.get("phone") or "").strip()

    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return {"status": "needs_permission", "error": f"cannot open chat.db: {e}"}

    try:
        if op == "send":
            to = handle or str(p.get("to") or "")
            body = str(p.get("text") or "")
            if not to or not body:
                return {"status": "failed", "error": "to and text required"}
            import subprocess

            script = f'''
            tell application "Messages"
              set targetService to 1st account whose service type = iMessage
              set targetBuddy to participant "{to}" of targetService
              send "{body.replace('"', '\\"')}" to targetBuddy
            end tell
            '''
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
            if r.returncode:
                return {"status": "failed", "error": (r.stderr or "send failed")[:400]}
            return {"status": "done", "result": {"sent": True, "to": to}}

        q = """
        SELECT m.text, m.is_from_me, m.date, h.id AS handle
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.text IS NOT NULL
        """
        args: list = []
        if handle:
            q += " AND h.id LIKE ?"
            args.append(f"%{handle}%")
        q += " ORDER BY m.date DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(q, args).fetchall()
        msgs = []
        for row in rows:
            # Apple epoch: nanoseconds since 2001-01-01
            ts = row["date"]
            when = None
            if ts:
                try:
                    when = datetime.fromtimestamp((ts / 1_000_000_000) + 978307200).isoformat()
                except Exception:
                    when = str(ts)
            msgs.append(
                {
                    "handle": row["handle"],
                    "text": row["text"],
                    "from_me": bool(row["is_from_me"]),
                    "at": when,
                }
            )
        return {"status": "done", "result": {"messages": msgs}}
    finally:
        conn.close()
