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
    PARSED_PAUSE_HOTKEY,
    PARSED_EXTRA_WAIT_HOTKEY,
    EXTRA_PAUSE_SECONDS,
    SPEAK_PAUSE_EVENTS,
)
from automation.core.audio import (
    speak,
    flash_console,
    play_pause_sound,
    play_resume_sound,
    play_extra_wait_sound,
)


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Pause state
_is_paused: bool = False
_is_auto_paused: bool = False

# Extra wait state
_extra_wait_until: datetime = datetime.min

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


def print_hotkey_info() -> None:
    """Print hotkey configuration information."""
    from automation.config import PAUSE_HOTKEY as _PAUSE_HOTKEY
    from automation.config import EXTRA_WAIT_HOTKEY as _EXTRA_WAIT_HOTKEY
    from automation.config import EXTRA_PAUSE_SECONDS as _EXTRA_PAUSE_SECONDS
    
    print("Hotkey configuration:")
    print(f"  {_PAUSE_HOTKEY} - Toggle pause/resume")
    print(f"  {_EXTRA_WAIT_HOTKEY} - Wait extra {_EXTRA_PAUSE_SECONDS} seconds")
    print("  (Using polled detection for reliability)")
