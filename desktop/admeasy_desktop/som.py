"""Set-of-mark: number clickable AX elements on the screenshot for the model."""
from __future__ import annotations

import base64
import io
from typing import Any

LAST_ELEMENTS: dict[int, dict[str, Any]] = {}
FRAME_SEQ = 0


def _clickable(el: dict) -> bool:
    role = (el.get("role") or "").lower()
    if role in ("button", "link", "textfield", "checkbox", "radiobutton", "menuitem", "tab"):
        return True
    name = (el.get("name") or "").strip()
    return bool(name) and role in ("statictext", "group", "image")


def annotate_screenshot(shot: dict, ax_elements: list[dict], logical_size: tuple[int, int] | None = None) -> dict:
    """Return shot with numbered marks; clicks use logical screen coordinates."""
    from PIL import Image, ImageDraw, ImageFont

    global LAST_ELEMENTS, FRAME_SEQ
    LAST_ELEMENTS = {}
    FRAME_SEQ += 1
    frame_id = f"f{FRAME_SEQ}"
    raw = base64.b64decode(shot["screenshot_b64"])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    sw, sh = img.size
    if logical_size:
        lw, lh = logical_size
    else:
        import pyautogui

        lw, lh = pyautogui.size()
    sx, sy = sw / max(lw, 1), sh / max(lh, 1)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    picked = [e for e in ax_elements if _clickable(e)][:40]
    elements: list[dict] = []
    for i, el in enumerate(picked, start=1):
        lx, ly, bw, bh = int(el["x"]), int(el["y"]), int(el["w"]), int(el["h"])
        cx, cy = lx + bw // 2, ly + bh // 2
        x, y = int(lx * sx), int(ly * sy)
        w, h = max(4, int(bw * sx)), max(4, int(bh * sy))
        icx, icy = x + w // 2, y + h // 2
        stable = f"{frame_id}:{i}"
        LAST_ELEMENTS[i] = {
            "cx": cx,
            "cy": cy,
            "mark": i,
            "stable_id": stable,
            "role": el.get("role"),
            "name": el.get("name"),
        }
        elements.append(
            {
                "id": i,
                "stable_id": stable,
                "frame_id": frame_id,
                "role": el.get("role"),
                "name": el.get("name"),
                "bounds": [lx, ly, bw, bh],
                "center": [cx, cy],
            }
        )
        draw.rectangle([x, y, x + w, y + h], outline="#ff2d95", width=2)
        draw.ellipse([icx - 10, icy - 10, icx + 10, icy + 10], fill="#ff2d95")
        draw.text((icx - 4, icy - 8), str(i), fill="white", font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=62)
    out = dict(shot)
    out["screenshot_b64"] = base64.b64encode(buf.getvalue()).decode()
    out["elements"] = elements
    out["ax_tree"] = ax_elements[:80]
    out["som"] = True
    out["frame_id"] = frame_id
    return out


def center_for_mark(element_id: int) -> tuple[int, int] | None:
    el = LAST_ELEMENTS.get(int(element_id))
    if not el:
        return None
    return int(el["cx"]), int(el["cy"])
