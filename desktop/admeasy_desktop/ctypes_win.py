"""Windows ctypes aliases missing from some Python builds (e.g. frozen 3.12 on Windows)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

# Python 3.12 on Windows may omit HCURSOR / HBRUSH from wintypes.
HCURSOR = getattr(wintypes, "HCURSOR", None) or wintypes.HANDLE
HBRUSH = getattr(wintypes, "HBRUSH", None) or wintypes.HANDLE
HICON = getattr(wintypes, "HICON", None) or wintypes.HANDLE
HINSTANCE = getattr(wintypes, "HINSTANCE", None) or wintypes.HANDLE
HANDLE = wintypes.HANDLE
LPCWSTR = getattr(wintypes, "LPCWSTR", None) or ctypes.c_wchar_p
