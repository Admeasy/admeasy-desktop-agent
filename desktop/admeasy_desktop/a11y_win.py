"""Windows UI Automation snapshot (optional uiautomation package)."""
from __future__ import annotations

from typing import Any


def snapshot(max_nodes: int = 80) -> list[dict[str, Any]]:
    try:
        import uiautomation as auto
    except ImportError:
        return []
    out: list[dict[str, Any]] = []
    root = auto.GetForegroundControl()
    if not root:
        return []

    def walk(ctrl, depth: int) -> None:
        if len(out) >= max_nodes or depth > 10:
            return
        try:
            rect = ctrl.BoundingRectangle
            name = (ctrl.Name or "")[:120]
            role = (ctrl.ControlTypeName or "Control").replace("Control", "")
            if rect.width() > 2 and rect.height() > 2:
                out.append(
                    {
                        "role": role,
                        "name": name,
                        "x": int(rect.left),
                        "y": int(rect.top),
                        "w": int(rect.width()),
                        "h": int(rect.height()),
                    }
                )
            for child in ctrl.GetChildren():
                walk(child, depth + 1)
        except Exception:
            return

    walk(root, 0)
    return out
