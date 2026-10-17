"""Optional menu-bar / system-tray icon (pause + quit). Skipped when pystray/Pillow are unavailable."""
from __future__ import annotations

import threading
from typing import Callable


def start_tray(paused: bool, on_pause: Callable[[bool], None], on_quit: Callable[[], None]) -> threading.Thread | None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None

    def icon_image(on: bool):
        img = Image.new("RGBA", (64, 64), (79, 70, 229, 255 if on else 120))
        d = ImageDraw.Draw(img)
        d.ellipse((16, 16, 48, 48), fill=(255, 255, 255, 220))
        return img

    state = {"paused": paused}

    def toggle(_icon, _item):
        state["paused"] = not state["paused"]
        on_pause(state["paused"])
        _icon.icon = icon_image(not state["paused"])

    def quit_app(_icon, _item):
        _icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem(lambda _: "Resume" if state["paused"] else "Pause", toggle),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("admeasy", icon_image(not paused), "Admeasy", menu)

    def run():
        icon.run()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
