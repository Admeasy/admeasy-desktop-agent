"""Call history, notifications, Continuity / Phone linkage (macOS-first)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

from .. import permissions


def run(p: dict) -> dict:
    op = p.get("op") or "notifications"
    limit = min(int(p.get("limit") or 25), 100)

    if op == "notifications":
        if sys.platform == "darwin":
            # Notification Center DB (macOS 12+)
            ndb = os.path.expanduser("~/Library/Group Containers/group.com.apple.usernoted/db2/db")
            if not permissions.can_read_full_disk() or not os.path.exists(ndb):
                return {
                    "status": "needs_permission",
                    "error": "Full Disk Access required to read recent notifications",
                }
            try:
                conn = sqlite3.connect(f"file:{ndb}?mode=ro", uri=True)
                rows = conn.execute(
                    "SELECT record.title, record.subtitle, record.body, record.delivered_date FROM record "
                    "ORDER BY record.delivered_date DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                conn.close()
                items = [{"title": r[0], "subtitle": r[1], "body": r[2], "at": r[3]} for r in rows]
                return {"status": "done", "result": {"notifications": items}}
            except sqlite3.Error as e:
                return {"status": "failed", "error": f"notifications db: {e}"}
        if sys.platform == "win32":
            return {
                "status": "done",
                "result": {"notifications": [], "note": "use Action Center APIs — not implemented in beta"},
            }
        return {"status": "done", "result": {"notifications": []}}

    if op == "calls":
        if sys.platform == "darwin":
            cdb = os.path.expanduser("~/Library/Application Support/CallHistoryDB/CallHistory.storedata")
            if not os.path.exists(cdb):
                cdb = os.path.expanduser("~/Library/Application Support/CallHistoryDB/CallHistory.sqlite")
            if not permissions.can_read_full_disk() or not os.path.exists(cdb):
                return {
                    "status": "needs_permission",
                    "error": "Full Disk Access required to read call history",
                }
            try:
                conn = sqlite3.connect(f"file:{cdb}?mode=ro", uri=True)
                # Schema varies by macOS version; best-effort generic query
                rows = conn.execute(
                    "SELECT ZADDRESS, ZDURATION, ZDATE FROM ZCALLRECORD ORDER BY ZDATE DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                conn.close()
                calls = [{"address": r[0], "duration_s": r[1], "at": r[2]} for r in rows]
                return {"status": "done", "result": {"calls": calls}}
            except sqlite3.Error:
                return {"status": "done", "result": {"calls": [], "note": "call history schema not readable on this macOS version"}}
        return {"status": "done", "result": {"calls": [], "platform": sys.platform}}

    if op == "continuity_call":
        if sys.platform != "darwin":
            return {"status": "failed", "error": "Continuity calls are macOS-only"}
        number = str(p.get("number") or p.get("handle") or "")
        if not number:
            return {"status": "failed", "error": "number required"}
        script = f'tell application "FaceTime" to open location "tel:{number}"'
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        if r.returncode:
            return {"status": "failed", "error": (r.stderr or "could not start call")[:300]}
        return {"status": "done", "result": {"dialed": number, "via": "continuity"}}

    return {"status": "failed", "error": f"unknown comms op {op}"}
