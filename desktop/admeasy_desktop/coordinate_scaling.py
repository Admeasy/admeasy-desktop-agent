"""Screenshot pixel space ↔ logical screen points (Retina scale, optional monitor origin)."""
from __future__ import annotations

MAX_EDGE = 1280
MAX_PIXELS = 1_150_000


class Scaler:
    """Map model coordinates in downscaled screenshot pixels to logical OS points."""

    def __init__(
        self,
        logical: tuple[int, int],
        physical: tuple[int, int],
        *,
        monitor_origin: tuple[int, int] = (0, 0),
    ):
        self.lw, self.lh = logical
        self.origin_x, self.origin_y = monitor_origin
        pw, ph = physical
        k = min(1.0, MAX_EDGE / max(pw, ph), (MAX_PIXELS / (pw * ph)) ** 0.5)
        self.w, self.h = max(1, int(pw * k)), max(1, int(ph * k))
        self.scale_x = self.lw / self.w
        self.scale_y = self.lh / self.h

    def to_logical(self, x: float, y: float) -> tuple[int, int]:
        x = min(max(x, 0), self.w - 1)
        y = min(max(y, 0), self.h - 1)
        lx = int(x * self.scale_x) + self.origin_x
        ly = int(y * self.scale_y) + self.origin_y
        return lx, ly
