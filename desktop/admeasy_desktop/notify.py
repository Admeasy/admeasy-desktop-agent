"""Native desktop toasts. The web window also shows a notification when it is open."""
from __future__ import annotations

import shutil
import subprocess
import sys


def toast(title: str, body: str) -> bool:
    title = (title or "Admeasy")[:80]
    body = (body or "")[:240]
    try:
        if sys.platform == "darwin":
            script = f"display notification { _as_string(body) } with title { _as_string(title) }"
            subprocess.Popen(["osascript", "-e", script])
            return True
        if sys.platform == "win32":
            # No extra package. A balloon via the built-in notification area is not
            # available headless; PowerShell's Windows Runtime toast works on Windows 10+.
            ps = (
                "$xml = @'\n"
                f"<toast><visual><binding template=\"ToastGeneric\">"
                f"<text>{_xml(title)}</text><text>{_xml(body)}</text>"
                f"</binding></visual></toast>\n"
                "'@; "
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                "$doc = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::new(); "
                "$doc.LoadXml($xml); "
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($doc); "
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Admeasy').Show($toast)"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
            return True
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, body])
            return True
    except Exception:
        return False
    return False


def _as_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _xml(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
