"""General tool manifest with JSON schemas for LangGraph binding (hello.capabilities.tools)."""

from __future__ import annotations

GENERAL_TOOLS: list[dict] = [
    {
        "name": "terminal",
        "description": "Persistent shell session per job (cwd and env survive between calls).",
        "kind": "terminal",
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"enum": ["run", "spawn", "write", "read", "close", "list"]},
                "command": {"type": "string"},
                "session_id": {"type": "string"},
                "data": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_s": {"type": "number", "description": "Per-call timeout (default 600, max 1800)."},
            },
            "required": ["op"],
        },
    },
    {
        "name": "files",
        "description": "Read, write, patch, search, list under user-allowed folders only.",
        "kind": "files",
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"enum": ["read", "write", "patch", "search", "list", "delete", "mkdir"]},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["op"],
        },
    },
    {
        "name": "screen",
        "description": "Screenshot plus set-of-mark click/type/scroll (computer use).",
        "kind": "screen",
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"enum": ["screenshot", "act"]},
                "action": {"type": "object"},
            },
            "required": ["op"],
        },
    },
    {
        "name": "browser",
        "description": "Attach to the user's Chrome/Edge/Brave via CDP when available, else Playwright profile.",
        "kind": "browser",
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"type": "string"},
                "url": {"type": "string"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "timeout_s": {"type": "number", "description": "Per browser call (max 1800)."},
                "cdp": {"type": "boolean", "description": "Prefer CDP attach to logged-in browser."},
            },
            "required": ["op"],
        },
    },
    {
        "name": "notify",
        "description": "Native desktop notification.",
        "kind": "notify",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["body"],
        },
    },
    {
        "name": "clipboard",
        "description": "Get or set clipboard text (set may require approval).",
        "kind": "clipboard",
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"enum": ["get", "set"]},
                "text": {"type": "string"},
            },
            "required": ["op"],
        },
    },
]

LEGACY_KIND_GROUPS: list[dict] = [
    {"group": "legacy", "kinds": ["whatsapp", "messages", "mail", "comms", "app", "ide", "cli", "signin"]},
]