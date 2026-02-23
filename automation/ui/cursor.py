"""
Low-level cursor manipulation using Win32 API.
"""

from __future__ import annotations

import ctypes
from datetime import datetime
from typing import Tuple, Optional

# ============================================================================
# WINDOWS API STRUCTURES
# ============================================================================

class POINT(ctypes.Structure):
    """Windows POINT structure for cursor position."""
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# ============================================================================
# GLOBAL STATE
# ============================================================================

_last_expected_cursor_pos: Optional[Tuple[int, int]] = None
_last_automation_cursor_set_at: Optional[datetime] = None


# ============================================================================
# CURSOR FUNCTIONS
# ============================================================================

def get_cursor_pos() -> Tuple[int, int]:
    """
    Get current mouse cursor position.
    
    Returns:
        (x, y) tuple
    """
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def _set_cursor_pos_raw(x: int, y: int) -> None:
    """Low-level Win32 SetCursorPos."""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def get_expected_cursor_pos() -> Optional[Tuple[int, int]]:
    """Return the last cursor position set/expected by automation."""
    return _last_expected_cursor_pos


def get_last_automation_cursor_set_at() -> Optional[datetime]:
    """Return when automation last set the cursor position."""
    return _last_automation_cursor_set_at


def set_expected_cursor_pos(pos: Tuple[int, int]) -> None:
    """Update the expected cursor position."""
    global _last_expected_cursor_pos
    _last_expected_cursor_pos = (int(pos[0]), int(pos[1]))


def mark_automation_cursor_set() -> None:
    """Record that automation just moved the cursor."""
    global _last_automation_cursor_set_at
    _last_automation_cursor_set_at = datetime.now()


def sync_expected_cursor_to_current() -> Optional[Tuple[int, int]]:
    """Treat the current cursor position as the automation baseline."""
    try:
        actual = get_cursor_pos()
        set_expected_cursor_pos(actual)
        return actual
    except Exception:
        return None
