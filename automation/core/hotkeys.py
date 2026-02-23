"""
Hotkey handling using Win32 API polling.

This module provides reliable hotkey detection using GetAsyncKeyState
polling instead of keyboard library hooks, which can be unreliable on Windows.

Key functions:
- check_hotkeys_polled(): Call frequently from main loop to detect hotkey presses
- toggle_pause(): Toggle automation pause state
- trigger_extra_wait(): Add extra wait time
"""

from __future__ import annotations

import ctypes
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from automation.config import (
    VK_CONTROL,
    VK_SHIFT,
    VK_MENU,
    VK_LWIN,
    VK_RWIN,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_ALT,
    MOD_WIN,
    PAUSE_HOTKEY,
    PARSED_PAUSE_HOTKEY,
    PARSED_EXTRA_WAIT_HOTKEY,
    EXTRA_PAUSE_SECONDS,
    SPEAK_PAUSE_EVENTS,
    # Mouse settings
    AUTO_PAUSE_ON_MOUSE_MOVE,
    MOUSE_MOVEMENT_THRESHOLD,
    MOUSE_PAUSE_SECONDS,
    AUTO_PAUSE_ON_CURSOR_DRIFT,
    CURSOR_DRIFT_THRESHOLD_PX,
    CURSOR_DRIFT_STABILITY_PX,
)
from automation.core.audio import (
    speak,
    flash_console,
    play_pause_sound,
    play_resume_sound,
    play_extra_wait_sound,
)
from automation.core.logging import log_verbose
from automation.ui.cursor import (
    get_cursor_pos,
    get_expected_cursor_pos,
    get_last_automation_cursor_set_at,
    sync_expected_cursor_to_current,
)


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Pause state
_is_paused: bool = False
_is_auto_paused: bool = False

# Extra wait state
_extra_wait_until: datetime = datetime.min

# Mouse detection state
_last_mouse_position: Optional[tuple[int, int]] = None
_mouse_pause_until: Optional[datetime] = None
_mouse_pause_active: bool = False
_physical_mouse_anchor: Optional[tuple[int, int]] = None

# Drift pause state
_drift_pause_active: bool = False
_drift_pause_until: Optional[datetime] = None
_drift_last_pos: Optional[tuple[int, int]] = None
_drift_next_check_at: datetime = datetime.min

# Callbacks for pause events
_on_pause_callback: Optional[Callable[[], None]] = None
_on_resume_callback: Optional[Callable[[], None]] = None


# ============================================================================
# STATE ACCESSORS
# ============================================================================

def is_paused() -> bool:
    """Check if automation is currently paused (manual or auto)."""
    return _is_paused or _is_auto_paused


def is_manually_paused() -> bool:
    """Check if automation is manually paused."""
    return _is_paused


def is_auto_paused() -> bool:
    """Check if automation is auto-paused (due to typing)."""
    return _is_auto_paused


def set_paused(paused: bool) -> None:
    """Set manual pause state."""
    global _is_paused
    _is_paused = paused


def set_auto_paused(paused: bool) -> None:
    """Set auto-pause state."""
    global _is_auto_paused
    _is_auto_paused = paused


def get_extra_wait_until() -> datetime:
    """Get the extra wait end time."""
    return _extra_wait_until


def set_extra_wait_until(until: datetime) -> None:
    """Set the extra wait end time."""
    global _extra_wait_until
    _extra_wait_until = until


def extra_wait_until() -> datetime:
    """Alias for get_extra_wait_until for backward compatibility."""
    return _extra_wait_until


def set_pause_callbacks(
    on_pause: Optional[Callable[[], None]] = None,
    on_resume: Optional[Callable[[], None]] = None,
) -> None:
    """Set callbacks to be called on pause/resume events."""
    global _on_pause_callback, _on_resume_callback
    _on_pause_callback = on_pause
    _on_resume_callback = on_resume


# ============================================================================
# WIN32 KEY STATE DETECTION
# ============================================================================

def _get_async_key_state(vk_code: int) -> bool:
    """Check if a key is currently pressed using GetAsyncKeyState."""
    state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
    # High bit set means key is currently pressed
    return (state & 0x8000) != 0


def is_keyboard_activity_detected() -> bool:
    """Return True if any common non-modifier key is currently pressed.

    This is intended as a safety signal that the user is interacting.
    """
    # Letters A-Z
    for vk in range(0x41, 0x5B):
        if _get_async_key_state(vk):
            return True

    # Digits 0-9
    for vk in range(0x30, 0x3A):
        if _get_async_key_state(vk):
            return True

    # Common navigation/edit keys
    common = [
        0x08,  # VK_BACK
        0x09,  # VK_TAB
        0x0D,  # VK_RETURN
        0x1B,  # VK_ESCAPE
        0x20,  # VK_SPACE
        0x21,  # VK_PRIOR (Page Up)
        0x22,  # VK_NEXT (Page Down)
        0x23,  # VK_END
        0x24,  # VK_HOME
        0x25,  # VK_LEFT
        0x26,  # VK_UP
        0x27,  # VK_RIGHT
        0x28,  # VK_DOWN
        0x2D,  # VK_INSERT
        0x2E,  # VK_DELETE
    ]
    for vk in common:
        if _get_async_key_state(vk):
            return True

    # Function keys F1-F12
    for vk in range(0x70, 0x7C):
        if _get_async_key_state(vk):
            return True

    return False


def _check_modifier_pressed(modifier: int) -> bool:
    """Check if a modifier combination is currently pressed."""
    if modifier & MOD_CONTROL:
        if not (_get_async_key_state(VK_CONTROL) or _get_async_key_state(0xA2) or _get_async_key_state(0xA3)):
            return False
    if modifier & MOD_SHIFT:
        if not (_get_async_key_state(VK_SHIFT) or _get_async_key_state(0xA0) or _get_async_key_state(0xA1)):
            return False
    if modifier & MOD_ALT:
        if not (_get_async_key_state(VK_MENU) or _get_async_key_state(0xA4) or _get_async_key_state(0xA5)):
            return False
    if modifier & MOD_WIN:
        if not (_get_async_key_state(VK_LWIN) or _get_async_key_state(VK_RWIN)):
            return False
    return True


# ============================================================================
# HOTKEY STATE TRACKING
# ============================================================================

@dataclass
class HotkeyState:
    """Track hotkey state to prevent repeated triggers."""
    pause_was_pressed: bool = False
    extra_wait_was_pressed: bool = False
    last_pause_trigger: datetime = datetime.min
    last_extra_wait_trigger: datetime = datetime.min
    debounce_seconds: float = 0.5  # Prevent re-trigger for this long


_hotkey_state = HotkeyState()


# ============================================================================
# PAUSE/RESUME ACTIONS
# ============================================================================

def toggle_pause() -> None:
    """Toggle pause state when hotkey is pressed."""
    global _is_paused, _is_auto_paused
    
    _is_paused = not _is_paused
    
    if _is_paused:
        _is_auto_paused = False  # Clear auto-pause when manually paused
        play_pause_sound()
        if SPEAK_PAUSE_EVENTS:
            speak("Paused")
        if _on_pause_callback:
            _on_pause_callback()
    else:
        play_resume_sound()
        if SPEAK_PAUSE_EVENTS:
            speak("Resumed")
        if _on_resume_callback:
            _on_resume_callback()
    
    flash_console()
    state = "PAUSED" if _is_paused else "RESUMED"
    print(f"\n{'='*50}")
    print(f"[{datetime.now()}] *** MANUAL {state} ***")
    print(f"{'='*50}\n")


def request_manual_pause(reason: str) -> None:
    """Force manual pause on (idempotent), with a reason."""
    global _is_paused, _is_auto_paused

    if _is_paused:
        # Already paused; still surface the reason.
        print(f"\n[{datetime.now()}] *** MANUAL PAUSED (already paused) ***")
        print(f"Reason: {reason}\n")
        return

    _is_paused = True
    _is_auto_paused = False
    play_pause_sound()
    if SPEAK_PAUSE_EVENTS:
        speak("Paused")
    if _on_pause_callback:
        _on_pause_callback()

    flash_console()
    print(f"\n{'='*50}")
    print(f"[{datetime.now()}] *** MANUAL PAUSED ***")
    print(f"Reason: {reason}")
    print(f"{'='*50}\n")


def trigger_extra_wait() -> None:
    """Add extra wait time when hotkey is pressed."""
    global _extra_wait_until
    
    _extra_wait_until = datetime.now() + timedelta(seconds=EXTRA_PAUSE_SECONDS)
    play_extra_wait_sound()
    flash_console()
    print(f"\n[{datetime.now()}] *** EXTRA WAIT: {EXTRA_PAUSE_SECONDS}s ***\n")


# ============================================================================
# MAIN POLLING FUNCTION
# ============================================================================

def check_hotkeys_polled() -> None:
    """
    Check for hotkeys using polling (GetAsyncKeyState).
    
    This is more reliable than keyboard library hooks on Windows.
    Call this frequently from the main loop (every 100ms or so).
    """
    global _hotkey_state
    
    now = datetime.now()
    
    # Get pre-parsed hotkeys
    pause_mods, pause_vk = PARSED_PAUSE_HOTKEY
    extra_mods, extra_vk = PARSED_EXTRA_WAIT_HOTKEY
    
    # Check pause hotkey (e.g., ctrl+shift+p)
    pause_pressed = _check_modifier_pressed(pause_mods) and _get_async_key_state(pause_vk)
    
    if pause_pressed and not _hotkey_state.pause_was_pressed:
        # Key just pressed (rising edge)
        if (now - _hotkey_state.last_pause_trigger).total_seconds() > _hotkey_state.debounce_seconds:
            _hotkey_state.last_pause_trigger = now
            toggle_pause()
    _hotkey_state.pause_was_pressed = pause_pressed
    
    # Check extra wait hotkey (e.g., ctrl+shift+w)
    extra_pressed = _check_modifier_pressed(extra_mods) and _get_async_key_state(extra_vk)
    
    if extra_pressed and not _hotkey_state.extra_wait_was_pressed:
        # Key just pressed (rising edge)
        if (now - _hotkey_state.last_extra_wait_trigger).total_seconds() > _hotkey_state.debounce_seconds:
            _hotkey_state.last_extra_wait_trigger = now
            trigger_extra_wait()
    _hotkey_state.extra_wait_was_pressed = extra_pressed

    # Also check mouse movement if enabled
    if AUTO_PAUSE_ON_MOUSE_MOVE:
        check_mouse_interrupts()


def check_mouse_interrupts() -> Optional[str]:
    """
    Check for mouse movement or drift and pause if detected.
    Returns a status string if in a drift pause, else None.
    """
    global _last_mouse_position, _mouse_pause_until, _mouse_pause_active
    global _physical_mouse_anchor, _drift_pause_active, _drift_pause_until
    global _drift_last_pos, _drift_next_check_at
    global _is_paused

    now = datetime.now()

    # If we're already in a mouse-triggered pause window, surface status so the
    # orchestrator can skip work immediately instead of relying solely on the
    # extra-wait timer. This guards cases where extra_wait_until wasn't honored
    # fast enough and clicking continued.
    if _mouse_pause_active and _mouse_pause_until and now < _mouse_pause_until:
        remaining = (_mouse_pause_until - now).total_seconds()
        return f"Mouse pause: {remaining:5.0f}s left | {PAUSE_HOTKEY} to resume"

    try:
        current_mouse_pos = get_cursor_pos()
    except Exception as exc:
        log_verbose(f"Failed to read cursor position: {exc}")
        current_mouse_pos = None

    if current_mouse_pos is None:
        return None

    # Ignore cursor deltas that likely come from automation itself.
    automation_set_at = get_last_automation_cursor_set_at()
    automation_recent = (
        automation_set_at is not None
        and (now - automation_set_at).total_seconds() <= 0.35
    )

    expected = get_expected_cursor_pos()
    baseline = expected if expected is not None else _last_mouse_position

    # 1. Cursor drift guard
    if AUTO_PAUSE_ON_CURSOR_DRIFT and expected is not None:
        dx = current_mouse_pos[0] - expected[0]
        dy = current_mouse_pos[1] - expected[1]
        distance = math.hypot(dx, dy)

        if distance >= CURSOR_DRIFT_THRESHOLD_PX:
            if not _drift_pause_active:
                if not is_paused():
                    request_manual_pause(
                        f"Cursor drift detected ({distance:.0f}px >= {CURSOR_DRIFT_THRESHOLD_PX}px)"
                    )
                _drift_pause_active = True
                _drift_last_pos = current_mouse_pos
                _drift_pause_until = now + timedelta(seconds=MOUSE_PAUSE_SECONDS)
                _drift_next_check_at = now

            if _drift_pause_active and is_paused():
                if now >= _drift_next_check_at:
                    try:
                        pos_now = get_cursor_pos()
                    except Exception:
                        pos_now = None

                    if pos_now is not None:
                        if _drift_last_pos is None:
                            _drift_last_pos = pos_now
                        else:
                            moved = math.hypot(
                                pos_now[0] - _drift_last_pos[0],
                                pos_now[1] - _drift_last_pos[1],
                            )
                            if moved >= CURSOR_DRIFT_STABILITY_PX:
                                _drift_last_pos = pos_now
                                _drift_pause_until = now + timedelta(seconds=MOUSE_PAUSE_SECONDS)
                    _drift_next_check_at = now + timedelta(seconds=1)

                remaining = max(0.0, (_drift_pause_until - now).total_seconds() if _drift_pause_until else 0.0)
                last = _drift_last_pos if _drift_last_pos is not None else current_mouse_pos
                
                if _drift_pause_until is not None and now >= _drift_pause_until:
                    if is_manually_paused():
                        set_paused(False)
                    _drift_pause_active = False
                    _drift_pause_until = None
                    _drift_last_pos = None
                    sync_expected_cursor_to_current()
                    print(f"\n[{now}] 🖱️  Cursor drift pause elapsed - resuming automation\n")
                    return None

                return f"Cursor drift pause: {remaining:5.0f}s left | last=({last[0]},{last[1]}) | {PAUSE_HOTKEY} to resume"

    # 2. Physical movement detector
    if baseline is not None:
        dx = current_mouse_pos[0] - baseline[0]
        dy = current_mouse_pos[1] - baseline[1]
        distance = math.hypot(dx, dy)

        if distance >= MOUSE_MOVEMENT_THRESHOLD:
            current_wait = get_extra_wait_until()
            pause_target = now + timedelta(seconds=MOUSE_PAUSE_SECONDS)
            
            if current_wait <= now or pause_target > current_wait:
                set_extra_wait_until(pause_target)
                reason = "extending" if _mouse_pause_active else "pausing"
                print(f"\n[{now}] 🖱️  Mouse moved {distance:.0f}px - {reason} automation for {MOUSE_PAUSE_SECONDS}s")
                if not _mouse_pause_active and SPEAK_PAUSE_EVENTS:
                    speak("Pausing automation")
                _mouse_pause_active = True
                _mouse_pause_until = pause_target

    _last_mouse_position = current_mouse_pos

    if not automation_recent:
        if _physical_mouse_anchor is None:
            _physical_mouse_anchor = current_mouse_pos
        else:
            dxp = current_mouse_pos[0] - _physical_mouse_anchor[0]
            dyp = current_mouse_pos[1] - _physical_mouse_anchor[1]
            physical_distance = math.hypot(dxp, dyp)

            if physical_distance >= MOUSE_MOVEMENT_THRESHOLD:
                pause_target = now + timedelta(seconds=MOUSE_PAUSE_SECONDS)
                set_extra_wait_until(pause_target)
                _mouse_pause_active = True
                _mouse_pause_until = pause_target
                _physical_mouse_anchor = current_mouse_pos
                print(f"\n[{now}] 🖱️  Physical mouse movement detected ({physical_distance:.0f}px) - pausing automation for {MOUSE_PAUSE_SECONDS}s")
                if SPEAK_PAUSE_EVENTS:
                    speak("Pausing automation")

    # Cleanup mouse pause state
    if _mouse_pause_active and _mouse_pause_until and now >= _mouse_pause_until:
        if get_extra_wait_until() <= now:
            _mouse_pause_active = False
            _mouse_pause_until = None
            print(f"[{now}] 🖱️  Mouse pause elapsed - resuming automation\n")
            if SPEAK_PAUSE_EVENTS:
                speak("Resumed")

    # If the user manually resumed, clear any drift status line state.
    if _drift_pause_active and not is_paused():
        _drift_pause_active = False
        _drift_pause_until = None
        _drift_last_pos = None
        sync_expected_cursor_to_current()

    return None


def print_hotkey_info() -> None:
    """Print hotkey configuration information."""
    from automation.config import PAUSE_HOTKEY as _PAUSE_HOTKEY
    from automation.config import EXTRA_WAIT_HOTKEY as _EXTRA_WAIT_HOTKEY
    from automation.config import EXTRA_PAUSE_SECONDS as _EXTRA_PAUSE_SECONDS
    
    print("Hotkey configuration:")
    print(f"  {_PAUSE_HOTKEY} - Toggle pause/resume")
    print(f"  {_EXTRA_WAIT_HOTKEY} - Wait extra {_EXTRA_PAUSE_SECONDS} seconds")
    print("  (Using polled detection for reliability)")
