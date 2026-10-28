"""Split an assistant reply into short chat bubbles.

The Lightsail backend stores one assistant message per turn (the same row WhatsApp
and the phone read). The desktop window presents that text as several bubbles.
"""
from __future__ import annotations

import re

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def fragment_reply(text: str, limit: int = 180) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    for para in re.split(r"\n\s*\n", raw):
        para = para.strip()
        if not para:
            continue
        # One sentence per bubble. A single short reply stays one bubble.
        for sentence in _SENTENCE.split(para):
            sentence = sentence.strip()
            if sentence:
                parts.append(sentence)
    out: list[str] = []
    for part in parts:
        if len(part) <= limit:
            out.append(part)
            continue
        start = 0
        while start < len(part):
            chunk = part[start:start + limit]
            if start + limit < len(part):
                cut = chunk.rfind(" ")
                if cut > 40:
                    chunk = chunk[:cut]
            chunk = chunk.strip()
            if chunk:
                out.append(chunk)
            start += max(len(chunk), 1)
    return out or [raw]
