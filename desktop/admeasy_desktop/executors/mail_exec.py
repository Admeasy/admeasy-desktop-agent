"""Mail.app (macOS) and Outlook / default client hooks."""
from __future__ import annotations

import subprocess
import sys


def run(p: dict) -> dict:
    op = p.get("op") or "unread"
    if sys.platform == "darwin":
        if op == "unread":
            script = """
            tell application "Mail"
              set n to unread count of inbox
              return n
            end tell
            """
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
            if r.returncode:
                return {"status": "failed", "error": (r.stderr or "Mail.app error")[:300]}
            try:
                count = int((r.stdout or "0").strip())
            except ValueError:
                count = 0
            return {"status": "done", "result": {"unread_inbox": count}}

        if op == "search":
            q = str(p.get("query") or "").replace('"', '\\"')
            script = f'''
            tell application "Mail"
              set foundMessages to (every message of inbox whose subject contains "{q}" or content contains "{q}")
              set outLines to {{}}
              repeat with m in items 1 thru (min 20 of (count of foundMessages)) of foundMessages
                set end of outLines to (subject of m) & " <" & (sender of m) & ">"
              end repeat
              return outLines as string
            end tell
            '''
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=45)
            lines = [ln for ln in (r.stdout or "").split(", ") if ln.strip()]
            return {"status": "done", "result": {"messages": lines[:20]}}

        if op == "compose":
            to = str(p.get("to") or "")
            subject = str(p.get("subject") or "").replace('"', '\\"')
            body = str(p.get("body") or "").replace('"', '\\"')
            script = f'''
            tell application "Mail"
              set newMessage to make new outgoing message with properties {{subject:"{subject}", content:"{body}" & return & return}}
              tell newMessage
                make new to recipient at end of to recipients with properties {{address:"{to}"}}
              end tell
              set visible of newMessage to true
              activate
            end tell
            '''
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
            if r.returncode:
                return {"status": "failed", "error": (r.stderr or "compose failed")[:300]}
            return {"status": "done", "result": {"composed": True, "to": to}}

        if op == "open":
            from . import system

            return system.open_target({"target": "Mail"})

    if sys.platform == "win32":
        if op == "open":
            from . import system

            return system.open_target({"target": "outlook:"})
        return {"status": "done", "result": {"note": "use Outlook COM in a future release", "op": op}}

    return {"status": "failed", "error": f"mail op {op} not supported on {sys.platform}"}
