"""Accessibility tree snapshot (macOS). Empty list elsewhere or without permission."""
from __future__ import annotations

import sys
from typing import Any


def snapshot(max_nodes: int = 80) -> list[dict[str, Any]]:
    if sys.platform != "darwin":
        return []
    try:
        import ApplicationServices as AS
        import Quartz
    except ImportError:
        return []

    app = AS.AXUIElementCreateSystemWide()
    err, focused = AS.AXUIElementCopyAttributeValue(app, AS.kAXFocusedApplicationAttribute, None)
    if err != AS.kAXErrorSuccess or focused is None:
        return []

    out: list[dict[str, Any]] = []

    def walk(el, depth: int) -> None:
        if len(out) >= max_nodes or depth > 12:
            return
        role = _attr(el, AS.kAXRoleAttribute) or ""
        title = _attr(el, AS.kAXTitleAttribute) or _attr(el, AS.kAXDescriptionAttribute) or ""
        pos = _attr(el, AS.kAXPositionAttribute)
        size = _attr(el, AS.kAXSizeAttribute)
        if pos is not None and size is not None:
            try:
                x, y = float(pos.x), float(pos.y)
                w, h = float(size.width), float(size.height)
            except Exception:
                x, y, w, h = 0, 0, 0, 0
        else:
            x, y, w, h = 0, 0, 0, 0
        if w > 2 and h > 2 and role:
            out.append(
                {
                    "role": str(role).replace("AX", ""),
                    "name": str(title)[:120],
                    "x": int(x),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                }
            )
        err, children = AS.AXUIElementCopyAttributeValue(el, AS.kAXChildrenAttribute, None)
        if err != AS.kAXErrorSuccess or not children:
            return
        for child in children[:40]:
            walk(child, depth + 1)

    walk(focused, 0)
    return out


def _attr(el, key):
    import ApplicationServices as AS

    err, val = AS.AXUIElementCopyAttributeValue(el, key, None)
    return val if err == AS.kAXErrorSuccess else None
