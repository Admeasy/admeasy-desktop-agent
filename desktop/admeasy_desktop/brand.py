"""Admeasy brand colors shared by on-screen overlays.

Product primary pink (`primaryPink` / mascot accent on web). Update here when design
tokens change; overlays import from this module only.
"""

# Web token `--pink` (#e278a0) from admeasy-ai-assistant web/src/styles.css. See ui/theme.css.
PRIMARY_PINK_HEX = "#e278a0"
PRIMARY_PINK_RGB = (226 / 255.0, 120 / 255.0, 160 / 255.0)

# Edge frame: ~10% opacity fill on strokes; pulse animates between these alphas.
EDGE_ALPHA_STATIC = 0.18
EDGE_ALPHA_PULSE_MIN = 0.12
EDGE_ALPHA_PULSE_MAX = 0.24
EDGE_WIDTH_PX = 3
PULSE_PERIOD_S = 3.5
