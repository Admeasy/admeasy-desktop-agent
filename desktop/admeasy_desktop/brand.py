"""Admeasy brand colors shared by on-screen overlays.

Product primary pink (`primaryPink` / mascot accent on web). Update here when design
tokens change; overlays import from this module only.
"""

# Canonical brand pink (web theme primaryPink).
PRIMARY_PINK_HEX = "#FF4D8D"
PRIMARY_PINK_RGB = (1.0, 77 / 255.0, 141 / 255.0)

# Edge frame: ~10% opacity fill on strokes; pulse animates between these alphas.
EDGE_ALPHA_STATIC = 0.18
EDGE_ALPHA_PULSE_MIN = 0.12
EDGE_ALPHA_PULSE_MAX = 0.24
EDGE_WIDTH_PX = 3
PULSE_PERIOD_S = 3.5
