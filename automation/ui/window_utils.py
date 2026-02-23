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
from automation.ui.cursor import (
    get_cursor_pos,
    _set_cursor_pos_raw,
    get_expected_cursor_pos,
    get_last_automation_cursor_set_at,
    set_expected_cursor_pos,
    mark_automation_cursor_set,
    sync_expected_cursor_to_current,
)
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
    exp = expected if expected is not None else get_expected_cursor_pos()

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
            from automation.core.hotkeys import request_manual_pause
            request_manual_pause(
                f"Cursor drift detected ({distance:.0f}px >= {CURSOR_DRIFT_THRESHOLD_PX}px) at '{label}'."
            )
            # Don't fight the user's mouse; abort the current UI action.
            raise RuntimeError("Cursor drift detected; automation paused")

    return actual


def set_cursor_pos(x: int, y: int) -> None:
    """
    Set mouse cursor position instantly.
    
    Args:
        x: X coordinate
        y: Y coordinate
    """
    # If the user moved the mouse away from where we last left it, pause before moving it again.
    cursor_checkpoint("before_set_cursor")
    _set_cursor_pos_raw(int(x), int(y))
    set_expected_cursor_pos((int(x), int(y)))
    mark_automation_cursor_set()
    cursor_checkpoint("after_set_cursor")


# ============================================================================
# WINDOWS API STRUCTURES
# ============================================================================

class LASTINPUTINFO(ctypes.Structure):
    """Windows LASTINPUTINFO structure for idle detection."""
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


# ============================================================================
# WINDOW FOCUS FUNCTIONS
# ============================================================================

def get_foreground_window() -> int:
    """
    Get the currently active/focused window handle.
    
    Returns:
        Window handle (HWND) of the foreground window
    """
    try:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


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


def get_root_window(hwnd: int | None) -> int:
    """Return the top-level (root) window for an HWND.

    Defensive against transient/invalid handles (e.g., `None`/0).
    """
    GA_ROOT = 2
    if not hwnd:
        return 0
    try:
        root = int(ctypes.windll.user32.GetAncestor(int(hwnd), GA_ROOT))
        return root or int(hwnd)
    except Exception:
        return int(hwnd or 0)


def force_foreground_window(hwnd: int) -> bool:
    """Best-effort bring an HWND to the foreground.

    Windows may reject plain SetForegroundWindow calls (focus-stealing rules).
    This routine tries a common Win32 recipe using ShowWindow/BringWindowToTop
    and temporary thread-input attachment.
    """

    hwnd = get_root_window(int(hwnd))
    if not hwnd:
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # Constants
    SW_RESTORE = 9

    def _get_thread_id(win_hwnd: int) -> int:
        try:
            return int(user32.GetWindowThreadProcessId(int(win_hwnd), 0))
        except Exception:
            return 0

    try:
        # Restore (in case minimized) and bring above others.
        try:
            # FIX: Only restore if actually minimized (IsIconic).
            # Unconditional SW_RESTORE causes maximized windows to un-maximize.
            if user32.IsIconic(int(hwnd)):
                user32.ShowWindow(int(hwnd), SW_RESTORE)
            # Original unconditional restore (causes layout issues):
            # user32.ShowWindow(int(hwnd), SW_RESTORE)
        except Exception:
            pass
        try:
            user32.BringWindowToTop(int(hwnd))
        except Exception:
            pass

        # First attempt: direct.
        try:
            user32.SetForegroundWindow(int(hwnd))
        except Exception:
            pass

        fg = get_foreground_window()
        if get_root_window(fg) == hwnd:
            return True

        # Second attempt: attach thread inputs.
        fg_tid = _get_thread_id(fg) if fg else 0
        target_tid = _get_thread_id(hwnd)
        cur_tid = int(kernel32.GetCurrentThreadId())

        attached_pairs: list[tuple[int, int]] = []

        def _attach(a: int, b: int) -> None:
            if not a or not b or a == b:
                return
            try:
                if bool(user32.AttachThreadInput(int(a), int(b), True)):
                    attached_pairs.append((a, b))
            except Exception:
                return

        _attach(fg_tid, target_tid)
        _attach(fg_tid, cur_tid)

        try:
            # FIX: Only restore if actually minimized.
            if user32.IsIconic(int(hwnd)):
                user32.ShowWindow(int(hwnd), SW_RESTORE)
            # Original unconditional restore (causes layout issues):
            # user32.ShowWindow(int(hwnd), SW_RESTORE)
        except Exception:
            pass
        try:
            user32.BringWindowToTop(int(hwnd))
        except Exception:
            pass
        try:
            user32.SetForegroundWindow(int(hwnd))
        except Exception:
            pass

        fg2 = get_foreground_window()
        return get_root_window(fg2) == hwnd
    finally:
        # Always detach in reverse order.
        try:
            for a, b in reversed(attached_pairs):
                try:
                    user32.AttachThreadInput(int(a), int(b), False)
                except Exception:
                    continue
        except Exception:
            pass


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
        # Clicking in-place; do NOT overwrite expected cursor position.
        # If the user moved the mouse away from where automation last left it, the
        # cursor drift guard should still be able to detect and pause.
        pass
    
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
