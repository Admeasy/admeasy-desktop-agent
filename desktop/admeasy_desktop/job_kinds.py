"""Job kinds and capability manifest (must match admeasy-ai-assistant app/devices/tools.py)."""

from __future__ import annotations

# Kinds the backend may send on /devices/tunnel.
JOB_KINDS = frozenset(
    {
        "screenshot",
        "open",
        "browser",
        "shell",
        "files",
        "clipboard",
        "cua",
        "terminal",
        "cli",
        "app",
        "ide",
        "whatsapp",
        "messages",
        "comms",
        "mail",
    }
)

# Human-readable tool surface for hello.capabilities.tools (mirrors backend tool groups).
TOOL_MANIFEST: list[dict] = [
    {"group": "screen", "kinds": ["screenshot", "cua"]},
    {"group": "shell", "kinds": ["shell", "terminal", "cli"]},
    {"group": "browser", "kinds": ["browser", "open"]},
    {"group": "files", "kinds": ["files", "clipboard"]},
    {"group": "apps", "kinds": ["app", "ide"]},
    {"group": "messaging", "kinds": ["whatsapp", "messages", "mail", "comms"]},
]
