"""
Window utility functions using Win32 API.

Provides low-level window manipulation without additional dependencies:
- Cursor position (get/set)
- Foreground window (get/set)
- System idle detection
"""

from __future__ import annotations

import ctypes
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

from automation.config import (
    AUTO_PAUSE_ON_CURSOR_DRIFT,
    CURSOR_DRIFT_THRESHOLD_PX,
    CURSOR_GUARD_LOG,
)
from automation.core.hotkeys import request_manual_pause
from automation.core.logging import log_verbose


@dataclass
class CursorCheckpoint:
    ts: str
    label: str
    actual: Tuple[int, int]
    expected: Optional[Tuple[int, int]]
    dx: Optional[int]
    dy: Optional[int]
    distance: Optional[float]


_last_expected_cursor_pos: Optional[Tuple[int, int]] = None


def get_expected_cursor_pos() -> Optional[Tuple[int, int]]:
    """Return the last cursor position set/expected by automation."""
    return _last_expected_cursor_pos


def _set_expected_cursor_pos(pos: Tuple[int, int]) -> None:
    global _last_expected_cursor_pos
    _last_expected_cursor_pos = (int(pos[0]), int(pos[1]))


def _mouse_guard_log_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "logs" / "mouse_guard.jsonl"


def _write_cursor_checkpoint(cp: CursorCheckpoint) -> None:
    if not CURSOR_GUARD_LOG:
        return
    try:
        path = _mouse_guard_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cp.__dict__, ensure_ascii=False) + "\n")
    except Exception as exc:
        log_verbose(f"Failed to write cursor checkpoint: {exc}")


def cursor_checkpoint(label: str, expected: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
    """Record a cursor checkpoint (and optionally detect drift). Returns actual cursor pos."""
    actual = get_cursor_pos()
    exp = expected if expected is not None else _last_expected_cursor_pos

    dx: Optional[int] = None
    dy: Optional[int] = None
    distance: Optional[float] = None
    if exp is not None:
        dx = int(actual[0] - exp[0])
        dy = int(actual[1] - exp[1])
        distance = float(math.hypot(dx, dy))

    cp = CursorCheckpoint(
        ts=datetime.now().isoformat(timespec="milliseconds"),
        label=label,
        actual=(int(actual[0]), int(actual[1])),
        expected=(int(exp[0]), int(exp[1])) if exp is not None else None,
        dx=dx,
        dy=dy,
        distance=distance,
    )
    _write_cursor_checkpoint(cp)

    if AUTO_PAUSE_ON_CURSOR_DRIFT and exp is not None and distance is not None:
        if distance >= float(CURSOR_DRIFT_THRESHOLD_PX):
            request_manual_pause(
                f"Cursor drift detected ({distance:.0f}px >= {CURSOR_DRIFT_THRESHOLD_PX}px) at '{label}'."
            )
            # Don't fight the user's mouse; abort the current UI action.
            raise RuntimeError("Cursor drift detected; automation paused")

    return actual


# ============================================================================
# WINDOWS API STRUCTURES
# ============================================================================

class POINT(ctypes.Structure):
    """Windows POINT structure for cursor position."""
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class LASTINPUTINFO(ctypes.Structure):
    """Windows LASTINPUTINFO structure for idle detection."""
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


# ============================================================================
# CURSOR FUNCTIONS
# ============================================================================

def get_cursor_pos() -> Tuple[int, int]:
    """
    Get current mouse cursor position.
    
    Returns:
        Tuple of (x, y) coordinates
    """
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def set_cursor_pos(x: int, y: int) -> None:
    """
    Set mouse cursor position instantly.
    
    Args:
        x: X coordinate
        y: Y coordinate
    """
    # If the user moved the mouse away from where we last left it, pause before moving it again.
    cursor_checkpoint("before_set_cursor")
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    _set_expected_cursor_pos((int(x), int(y)))
    cursor_checkpoint("after_set_cursor")


# ============================================================================
# WINDOW FOCUS FUNCTIONS
# ============================================================================

def get_foreground_window() -> int:
    """
    Get the currently active/focused window handle.
    
    Returns:
        Window handle (HWND) of the foreground window
    """
    return ctypes.windll.user32.GetForegroundWindow()


def set_foreground_window(hwnd: int) -> bool:
    """
    Set the active/focused window by handle.
    
    Args:
        hwnd: Window handle to bring to foreground
        
    Returns:
        True if successful
    """
    try:
        return bool(ctypes.windll.user32.SetForegroundWindow(int(hwnd)))
    except Exception:
        return False


def get_console_window() -> int:
    """
    Get the console window handle.
    
    Returns:
        Window handle of the console window
    """
    return ctypes.windll.kernel32.GetConsoleWindow()


# ============================================================================
# IDLE DETECTION
# ============================================================================

def _get_tick_count_ms() -> int:
    """Return the system tick count in milliseconds."""
    try:
        return ctypes.windll.kernel32.GetTickCount64()
    except AttributeError:
        # Fall back to 32-bit counter on older systems
        return ctypes.windll.kernel32.GetTickCount()


def get_system_idle_seconds() -> Optional[float]:
    """
    Return seconds since the last user input event (keyboard or mouse).
    
    Uses Windows GetLastInputInfo API.
    
    Returns:
        Seconds since last input, or None if detection failed
    """
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None

        now_ms = _get_tick_count_ms()
        idle_ms = int(now_ms) - int(info.dwTime)
        if idle_ms < 0:
            idle_ms += 2 ** 32  # Handle 32-bit wraparound
        return idle_ms / 1000.0
    except Exception:
        return None


# ============================================================================
# MOUSE CLICK SIMULATION
# ============================================================================

def send_mouse_click(x: Optional[int] = None, y: Optional[int] = None) -> None:
    """
    Send a mouse click at the specified position (or current position).
    
    Args:
        x: X coordinate (optional, uses current if not specified)
        y: Y coordinate (optional, uses current if not specified)
    """
    cursor_checkpoint("before_click")
    if x is not None and y is not None:
        set_cursor_pos(x, y)
    else:
        # Clicking in-place; update expectation to current position.
        pos = get_cursor_pos()
        _set_expected_cursor_pos(pos)
    
    # Mouse button down
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    # Mouse button up
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

    cursor_checkpoint("after_click")


# ============================================================================
# WINDOW RECTANGLE
# ============================================================================

class RECT(ctypes.Structure):
    """Windows RECT structure."""
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """
    Get the bounding rectangle of a window.
    
    Args:
        hwnd: Window handle
        
    Returns:
        Tuple of (left, top, right, bottom) or None if failed
    """
    rect = RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return None
