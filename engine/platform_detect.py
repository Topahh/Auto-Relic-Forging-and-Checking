"""
engine/platform_detect.py
─────────────────────────
Runtime platform / display-server detection for hajiwo.

Usage
-----
    from engine.platform_detect import Platform, detect_platform

    plat = detect_platform()          # called once, cached after that
    if plat == Platform.WAYLAND:
        ...
    elif plat == Platform.WINDOWS:
        ...

The singleton is stored in _PLATFORM_CACHE so the detection runs only
once per process (first call to detect_platform()).
"""

import os
import sys
from enum import Enum, auto
from typing import Optional


# ──────────────────────────────────────────────────────────────────
# Platform enum
# ──────────────────────────────────────────────────────────────────

class Platform(Enum):
    WINDOWS = auto()   # Win32 — uses pyautogui / pydirectinput
    WAYLAND = auto()   # Linux Wayland — uses ScreenCast helper + xdotool
    X11     = auto()   # Linux X11 — uses pyautogui + xdotool (future-proof)
    UNKNOWN = auto()   # Fallback — warn and try best-effort


# ──────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────

_PLATFORM_CACHE: Optional[Platform] = None


def _detect() -> Platform:
    """
    Probe the current environment and return the most specific Platform.

    Detection order (first match wins):
      1. Windows  →  sys.platform == 'win32'
      2. Wayland  →  WAYLAND_DISPLAY env var is set   ← most reliable
                     OR XDG_SESSION_TYPE == 'wayland'
      3. X11      →  DISPLAY env var set / XDG_SESSION_TYPE == 'x11'
      4. UNKNOWN  →  fallback
    """
    if sys.platform == "win32":
        return Platform.WINDOWS

    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    xdg_session     = os.environ.get("XDG_SESSION_TYPE", "").lower()

    if wayland_display or xdg_session == "wayland":
        return Platform.WAYLAND

    display = os.environ.get("DISPLAY", "")
    if display or xdg_session == "x11":
        return Platform.X11

    return Platform.UNKNOWN


def detect_platform() -> Platform:
    """Return the current Platform (cached after first call)."""
    global _PLATFORM_CACHE
    if _PLATFORM_CACHE is not None:
        return _PLATFORM_CACHE

    p = _detect()
    _PLATFORM_CACHE = p

    _BANNERS = {
        Platform.WINDOWS: "[PLATFORM] Windows detected   → pyautogui / pydirectinput backend",
        Platform.WAYLAND: "[PLATFORM] Linux Wayland detected → ScreenCast helper + xdotool backend",
        Platform.X11:     "[PLATFORM] Linux X11 detected     → pyautogui + xdotool backend",
        Platform.UNKNOWN: "[PLATFORM] WARNING: unknown display server — falling back to pyautogui",
    }
    print(_BANNERS[p])
    return p


def is_windows() -> bool:
    return detect_platform() == Platform.WINDOWS

def is_wayland() -> bool:
    return detect_platform() == Platform.WAYLAND

def is_x11() -> bool:
    return detect_platform() == Platform.X11