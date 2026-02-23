"""
Button clicking utilities with verification and retry logic.

Provides reliable button clicking that:
- Teleports mouse to avoid animation delays
- Verifies button was dismissed after clicking
- Retries with multiple click methods if needed
- Preserves user's mouse position and window focus
- Tracks Try Again clicks to detect server-side rate limiting
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING, List

import uiautomation as auto

from automation.ui.window_utils import (
    get_cursor_pos,
    set_cursor_pos,
    get_foreground_window,
    set_foreground_window,
    send_mouse_click,
    get_root_window,
    force_foreground_window,
)
from automation.ui.scroll import scroll_control_into_view
from automation.config import (
    VSCODE_TITLE_SUFFIX,
    TRY_AGAIN_COOLDOWN_MINUTES,
    IGNORE_KEEP_BUTTONS,
)

from automation.title_parsing import is_vscode_window_title
from automation.core.logging import log_verbose

if TYPE_CHECKING:
    pass


# ============================================================================
# CLICK SAFETY CONSTANTS
# ============================================================================

MAX_BOUNDS_RETRIES = 4
BOUNDS_INITIAL_DELAY = 1.0  # seconds
BOUNDS_MAX_DELAY = 5.0  # seconds


def _new_method_stat() -> dict[str, int]:
    """Factory for click method metrics."""
    return {"success": 0, "fail": 0}


_click_method_stats: defaultdict[str, dict[str, int]] = defaultdict(_new_method_stat)


def _window_stat_factory() -> dict[str, int]:
    """Factory for per-window approval counts."""
    return {"allow": 0, "keep_edits": 0, "try_again": 0}


_window_approval_stats: defaultdict[str, dict[str, int]] = defaultdict(_window_stat_factory)


def _get_window_handle(control: auto.Control) -> int:
    """Return the native window handle for a VS Code window control."""

    def _extract_handle(ctrl: Optional[auto.Control]) -> int:
        if not ctrl:
            return 0
        try:
            handle = getattr(ctrl, "NativeWindowHandle", 0)
            hwnd = int(handle or 0)
            return get_root_window(hwnd) if hwnd else 0
        except Exception:
            return 0

    hwnd = _extract_handle(control)
    if hwnd:
        return hwnd

    # Walk up the parent chain to find a window handle.
    parent: Optional[auto.Control] = None
    try:
        parent = control.GetParentControl()
    except Exception:
        parent = None

    depth = 0
    while parent and depth < 12:
        hwnd = _extract_handle(parent)
        if hwnd:
            return hwnd
        try:
            parent = parent.GetParentControl()
        except Exception:
            parent = None
        depth += 1

    # Fallback: match by window title against top-level windows.
    title = ""
    try:
        title = control.Name or ""
    except Exception:
        title = ""

    if title:
        try:
            for root in auto.GetRootControl().GetChildren():
                if not isinstance(root, (auto.WindowControl, auto.PaneControl)):
                    continue
                try:
                    if (root.Name or "") == title:
                        hwnd = _extract_handle(root)
                        if hwnd:
                            return hwnd
                except Exception:
                    continue
        except Exception:
            pass

    return 0


def _foreground_title_matches(title: str) -> bool:
    if not title:
        return False
    try:
        fg = get_foreground_window()
        if not fg:
            return False
        ctrl = auto.ControlFromHandle(int(fg))
        return (ctrl.Name or "") == title
    except Exception:
        return False


def _maybe_switch_to_window_desktop(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        from automation.desktop.window_cache import get_desktop_for_handle
        from automation.desktop.switcher import needs_desktop_switch, switch_to_desktop
    except Exception:
        return False

    try:
        desktop = get_desktop_for_handle(hwnd)
    except Exception:
        desktop = None

    if desktop is None:
        return False

    try:
        if needs_desktop_switch(desktop):
            switch_to_desktop(desktop)
            time.sleep(0.5)
            return True
    except Exception:
        return False

    return False


FOCUS_RETRY_DELAY = 0.5


def ensure_window_focus(
    vs_win: auto.Control,
    *,
    description: str = "",
    retries: int = 2,
) -> bool:
    """Best-effort attempt to ensure the provided window has focus."""
    hwnd = _get_window_handle(vs_win)
    title = ""
    try:
        title = vs_win.Name or ""
    except Exception:
        title = ""

    if hwnd:
        _maybe_switch_to_window_desktop(hwnd)
    elif title and _foreground_title_matches(title):
        return True

    for attempt in range(1, retries + 1):
        try:
            current = get_foreground_window()
        except Exception:
            current = 0

        current = int(current or 0)

        if hwnd and get_root_window(current) == hwnd:
            return True
        if title and _foreground_title_matches(title):
            return True

        try:
            vs_win.SetActive()  # type: ignore[attr-defined]
            time.sleep(0.05)
        except Exception:
            pass

        # Prefer a stronger focus path; fall back to plain SetForegroundWindow.
        if hwnd:
            try:
                force_foreground_window(hwnd)
            except Exception:
                set_foreground_window(hwnd)
        time.sleep(FOCUS_RETRY_DELAY * attempt)

        try:
            if hwnd and get_root_window(int(get_foreground_window() or 0)) == hwnd:
                return True
        except Exception:
            pass

        if title and _foreground_title_matches(title):
            return True

        if attempt == retries and hwnd:
            if _maybe_switch_to_window_desktop(hwnd):
                time.sleep(0.1)
                try:
                    vs_win.SetActive()  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    force_foreground_window(hwnd)
                except Exception:
                    set_foreground_window(hwnd)
                time.sleep(FOCUS_RETRY_DELAY)
                try:
                    if get_root_window(int(get_foreground_window() or 0)) == hwnd:
                        return True
                except Exception:
                    pass

    if description:
        fg_hwnd = get_foreground_window() or 0
        fg_title = ""
        try:
            fg_ctrl = auto.ControlFromHandle(int(fg_hwnd))
            fg_title = fg_ctrl.Name or ""
        except Exception:
            pass
            
        print(
            f"  [WARN] Unable to focus '{description[:60]}' after {retries} attempt(s)."
            f" Foreground: '{fg_title[:60]}' ({fg_hwnd}). Skipping sensitive UI automation."
        )
    return False


# ============================================================================
# RATE LIMIT DETECTION VIA TRY AGAIN BUTTONS
# ============================================================================

# Cooldown state triggered by Try Again detection
_try_again_cooldown_until: datetime = datetime.min

# Seconds to wait after an Allow click to check for Try Again
POST_ALLOW_CHECK_DELAY = 2.0


def trigger_rate_limit_cooldown(window_title: str) -> None:
    """
    Trigger rate limit cooldown when a Try Again button is detected after an Allow click.
    
    Args:
        window_title: Title of the VS Code window where rate limit was detected
    """
    global _try_again_cooldown_until
    
    now = datetime.now()
    _try_again_cooldown_until = now + timedelta(minutes=TRY_AGAIN_COOLDOWN_MINUTES)
    
    # Also update the global cooldown system
    try:
        from automation.rate_limit.cooldown import start_cooldown
        start_cooldown(now, {window_title})
    except ImportError:
        pass
    
    # Speak alert for rate limit
    try:
        from automation.core.audio import speak
        speak("Rate limited. Waiting 5 minutes.")
    except ImportError:
        pass
    
    print(f"\n🔴 RATE LIMITED! 'Try Again' button appeared after Allow click.")
    print(f"   Window: {window_title[:60]}...")
    print(f"   Entering {TRY_AGAIN_COOLDOWN_MINUTES} minute cooldown until {_try_again_cooldown_until.strftime('%H:%M:%S')}")


def is_try_again_cooldown_active() -> bool:
    """Check if the Try Again cooldown is currently active."""
    return datetime.now() < _try_again_cooldown_until


def get_try_again_cooldown_remaining() -> float:
    """Get seconds remaining in Try Again cooldown."""
    remaining = (_try_again_cooldown_until - datetime.now()).total_seconds()
    return max(0.0, remaining)


def get_try_again_count_in_window() -> int:
    """Legacy function - no longer tracking count, returns 0."""
    return 0


def check_for_try_again_button(vs_win: auto.Control, max_depth: int = 50) -> bool:
    """
    Check if a Try Again button exists in the window (indicates rate limiting).
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth
        
    Returns:
        True if a Try Again button is found
    """
    try:
        # Quick search for Try Again button
        try_again_btn = vs_win.ButtonControl(searchDepth=max_depth, Name="Try Again")
        if try_again_btn.Exists(0.1):
            return True
        
        # Also check for the variant with keyboard shortcut
        try_again_btn2 = vs_win.ButtonControl(searchDepth=max_depth, Name="Try Again (Ctrl+Enter)")
        if try_again_btn2.Exists(0.1):
            return True
    except Exception:
        pass
    
    return False


def has_valid_bounds(control: auto.Control) -> bool:
    """
    Check if a control has valid (non-zero) bounding rectangle.
    
    Args:
        control: UI control to check
        
    Returns:
        True if the control has a valid visible rectangle
    """
    try:
        rect = control.BoundingRectangle
        # Check for zero bounds
        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            return False
        # Check for non-positive size
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return False
        return True
    except Exception:
        return False


def invoke_control(control: auto.Control) -> bool:
    """
    Attempt to activate a control via Invoke pattern when clicking isn't possible.
    
    Args:
        control: UI control to invoke
        
    Returns:
        True if invoke succeeded
    """
    try:
        getter = getattr(control, "GetInvokePattern", None)
        if callable(getter):
            invoke_pattern = getter()
            if invoke_pattern:
                invoke_pattern.Invoke()
                return True
    except Exception:
        pass
    return False


def _record_method_attempt(
    method: str,
    success: bool,
    button_name: str,
    window_title: str,
    *,
    detail: str = "",
) -> None:
    """Log and tally click method attempts."""
    stats = _click_method_stats[method]
    stats["success" if success else "fail"] += 1
    stamp = datetime.now().strftime("%H:%M:%S")
    status = "✓" if success else "✗"
    extra = f" | {detail}" if detail else ""
    print(
        f"[{stamp}] {status} {method.upper()} for '{button_name}' in '{window_title}'"
        f" (bounds stats: {stats['success']} ok/{stats['fail']} fail){extra}"
    )


def _extract_keyboard_shortcut(button_name: str) -> Optional[str]:
    """Return SendKeys-friendly shortcut for recognized button names."""
    lowered = button_name.lower()
    if "ctrl+enter" in lowered:
        return "^{ENTER}"
    if "shift+enter" in lowered and "ctrl" in lowered:
        return "^+{ENTER}"
    if "alt+enter" in lowered:
        return "%{ENTER}"
    return None


def _send_keyboard_shortcut(
    btn: auto.Control,
    button_name: str,
    window_title: str,
) -> bool:
    """Send the shortcut embedded in the button label, if any."""
    shortcut = _extract_keyboard_shortcut(button_name)
    if not shortcut:
        return False

    try:
        vs_code_window = _find_parent_vscode_window(btn)
        if vs_code_window:
            try:
                vs_code_window.SetActive()  # type: ignore[attr-defined]
                time.sleep(0.05)
            except Exception:
                pass

        try:
            btn.SetFocus()
            time.sleep(0.02)
        except Exception:
            pass

        auto.SendKeys(shortcut)
        _record_method_attempt("keyboard", True, button_name, window_title, detail=f"shortcut={shortcut}")
        return True
    except Exception as exc:
        _record_method_attempt("keyboard", False, button_name, window_title, detail=str(exc))
        return False


def _await_visible_bounds(btn: auto.Control, button_name: str, window_title: str) -> bool:
    """Poll for a control to expose valid bounds with exponential backoff."""
    try:
        vs_code_window = _find_parent_vscode_window(btn)
    except Exception:
        vs_code_window = None

    if vs_code_window:
        try:
            vs_code_window.SetActive()  # type: ignore[attr-defined]
            time.sleep(0.05)
        except Exception:
            pass

    for attempt in range(1, MAX_BOUNDS_RETRIES + 1):
        if has_valid_bounds(btn):
            if attempt > 1:
                print(
                    f"  [READY] Bounds for '{button_name}' stabilized after {attempt} attempt(s)."
                )
            return True
        delay = min(BOUNDS_INITIAL_DELAY * (2 ** (attempt - 1)), BOUNDS_MAX_DELAY)
        print(
            f"  [WAIT] Bounds unavailable for '{button_name}' in '{window_title}'"
            f" – retrying in {delay:.1f}s (attempt {attempt}/{MAX_BOUNDS_RETRIES})."
        )
        try:
            scroll_control_into_view(btn)
        except Exception:
            pass
        time.sleep(delay)
    return False


def _find_parent_vscode_window(control: auto.Control) -> Optional[auto.Control]:
    """Find the parent VS Code window of a control."""
    try:
        parent = control.GetParentControl()
        depth = 0
        while parent and depth < 15:
            if isinstance(parent, (auto.WindowControl, auto.PaneControl)):
                name = parent.Name or ""
                if is_vscode_window_title(name):
                    return parent
            parent = parent.GetParentControl()
            depth += 1
    except Exception:
        pass
    return None


def _resolve_click_point(btn: auto.Control) -> Optional[tuple[int, int]]:
    """Best-effort way to get a clickable point even when bounds are zero."""

    def rect_center(rect) -> Optional[tuple[int, int]]:
        try:
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return None
            return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
        except Exception:
            return None

    # First attempt: normal bounding rectangle
    try:
        rect = btn.BoundingRectangle
    except Exception:
        rect = None

    if rect and rect_center(rect):
        return rect_center(rect)

    # Try to bring the control into view and re-read bounds
    scroll_control_into_view(btn)
    time.sleep(0.1)
    try:
        rect = btn.BoundingRectangle
    except Exception:
        rect = None

    center = rect_center(rect) if rect else None
    if center:
        return center

    # Fallback: ask UIA for a clickable point
    try:
        pt = btn.GetClickablePoint()
        if pt:
            return int(pt[0]), int(pt[1])
    except Exception:
        pass

    # Final fallback: use parent's bounds
    try:
        parent = btn.GetParentControl()
        if parent and has_valid_bounds(parent):
            rect = parent.BoundingRectangle
            return rect_center(rect)
    except Exception:
        pass

    return None


def click_button_instantly(btn: auto.Control) -> None:
    """
    Click a button by instantly teleporting the mouse to it and back.
    
    Saves and restores:
    - Mouse position
    - Active window focus
    
    Uses direct Win32 API calls for instant movement without animation.
    
    Args:
        btn: Button control to click
    """
    # 2026-01-18: Invoke-First Strategy
    # Attempt to use the InvokePattern (programmatic click) BEFORE moving the mouse.
    # This prevents "teleport spam" (cursor jumping back and forth) when checking
    # multiple candidates or when controls have invalid bounds (0x0).
    try:
        button_name_safe = btn.Name or "<unnamed>"
    except Exception:
        button_name_safe = "<unnamed>"
        
    # Get window title for logging/stats context
    try:
        raw_title = btn.GetTopLevelControl().Name
        window_title_safe = raw_title if raw_title else "Unknown"
    except Exception:
        window_title_safe = "Unknown"

    # Try Invoke/Toggle patterns first
    if invoke_control(btn):
        _record_method_attempt("invoke-first", True, button_name_safe, window_title_safe)
        return

    # If programmatic invoke fails, fall back to physical mouse click.
    # This requires valid bounds and cursor movement.

    # Save current mouse position AND active window
    original_pos = get_cursor_pos()
    original_window = get_foreground_window()

    try:
        try:
            button_name = btn.Name or "<unnamed>"
        except Exception:
            button_name = "<unnamed>"

        vs_code_window = _find_parent_vscode_window(btn)
        window_title = "Unknown"
        if vs_code_window:
            try:
                window_title = vs_code_window.Name or "Unknown"
            except Exception:
                window_title = "Unknown"
            try:
                vs_code_window.SetActive()  # type: ignore[attr-defined]
                time.sleep(0.05)
            except Exception:
                pass

        bounds_ready = _await_visible_bounds(btn, button_name, window_title)

        click_point = None
        if bounds_ready:
            click_point = _resolve_click_point(btn)

        if not bounds_ready or not click_point:
            print(
                f"[{datetime.now()}] Warning: '{button_name}' has no usable bounds;"
                " preferring non-mouse fallbacks."
            )
            if _send_keyboard_shortcut(btn, button_name, window_title):
                return
            if invoke_control(btn):
                _record_method_attempt("invoke", True, button_name, window_title)
                return
            _record_method_attempt("invoke", False, button_name, window_title, detail="no patterns")
            raise RuntimeError("No clickable point or fallback for control")

        center_x, center_y = click_point

        # Instantly move mouse to button center
        set_cursor_pos(center_x, center_y)
        time.sleep(0.02)

        # Try multiple click methods for reliability
        click_succeeded = False

        # Method 1: Standard UIAutomation click
        try:
            btn.Click(simulateMove=False)
            click_succeeded = True
            _record_method_attempt("mouse", True, button_name, window_title, detail="uia-click")
        except Exception as exc:
            _record_method_attempt("mouse", False, button_name, window_title, detail=str(exc))

        # Method 2: Invoke pattern fallback
        if not click_succeeded:
            if invoke_control(btn):
                click_succeeded = True
                _record_method_attempt("invoke", True, button_name, window_title)
            else:
                _record_method_attempt("invoke", False, button_name, window_title, detail="pattern missing")

        # Method 3: Keyboard shortcut fallback
        if not click_succeeded:
            if _send_keyboard_shortcut(btn, button_name, window_title):
                click_succeeded = True

        # Method 4: Physical mouse click via Win32
        if not click_succeeded:
            try:
                send_mouse_click()
                click_succeeded = True
                _record_method_attempt("mouse", True, button_name, window_title, detail="win32-click")
            except Exception as exc:
                _record_method_attempt("mouse", False, button_name, window_title, detail=f"win32:{exc}")

        if not click_succeeded:
            raise RuntimeError(f"Unable to activate '{button_name}' in '{window_title}'")

    finally:
        # Restore mouse to original position
        time.sleep(0.05)
        set_cursor_pos(original_pos[0], original_pos[1])

        # Restore the original active window
        if original_window:
            time.sleep(0.05)
            set_foreground_window(original_window)


def control_no_longer_visible(ctrl: auto.Control) -> bool:
    """
    Check if a control no longer exists or is no longer visible.
    
    Args:
        ctrl: Control to check
        
    Returns:
        True if the control is gone or invalid
    """
    try:
        if not ctrl.Exists(0.2):
            return True
        
        # Verify the button still has valid bounds
        if not has_valid_bounds(ctrl):
            return True
        
        # Check if button is still enabled
        try:
            if not ctrl.IsEnabled:
                return True
        except Exception:
            pass
        
        return False
    except Exception:
        return True


def click_button_with_verification(
    btn: auto.Control,
    description: str,
    *,
    max_attempts: int = 3,
    post_click_wait: float = 0.3,
) -> bool:
    """
    Click a button and verify it disappeared before proceeding.
    
    Retries up to max_attempts times when the control still exists.
    
    Args:
        btn: Button control to click
        description: Description for logging (e.g., "Allow button")
        max_attempts: Maximum click attempts
        post_click_wait: Seconds to wait after each click
        
    Returns:
        True if the button was successfully clicked (and disappeared)
    """
    for attempt in range(1, max_attempts + 1):
        try:
            click_button_instantly(btn)
        except Exception as exc:
            if attempt >= max_attempts:
                print(f"  ✗ Failed to click {description} after {attempt} attempt(s): {exc}")
                return False
            print(f"  ⚠ Error clicking {description} (attempt {attempt}): {exc}. Retrying...")
            time.sleep(0.15)
            continue

        # Wait progressively longer after each attempt
        wait_time = post_click_wait * (1 + (attempt - 1) * 0.5)
        time.sleep(wait_time)
        
        # Check multiple times with small delays for slow UI updates
        button_gone = False
        for _ in range(3):
            if control_no_longer_visible(btn):
                button_gone = True
                break
            time.sleep(0.1)
        
        if button_gone:
            if attempt > 1:
                print(f"  ✓ {description} registered after {attempt} attempts.")
            return True

        if attempt < max_attempts:
            print(f"  ⚠ {description} still detected after attempt {attempt}; trying again...")
            scroll_control_into_view(btn)
            time.sleep(0.08)
        else:
            print(f"  ⚠ {description} still present after {max_attempts} attempts; moving on.")
            # NOTE: Keyboard shortcut fallback disabled - it can accidentally type '^' 
            # characters into the chat when focus/timing is off
            # try:
            #     print("  → Trying keyboard shortcut Ctrl+Enter as fallback...")
            #     auto.SendKeys('^{Enter}')
            #     time.sleep(0.3)
            #     if control_no_longer_visible(btn):
            #         print(f"  ✓ {description} dismissed via keyboard shortcut.")
            #         return True
            # except Exception as e:
            #     print(f"  ✗ Keyboard fallback also failed: {e}")

    return False


def click_all_action_buttons(vs_win: auto.Control) -> tuple:
    """
    Click all Allow, Keep Edits, and Try Again buttons in a VS Code window.
    
    Rate limit detection:
    - After clicking Allow, waits 2s to check if Try Again button appears
    - After clicking Try Again, waits 2s to check if another Try Again appears
    - If Try Again persists/reappears, we're rate limited → 5-minute cooldown
    
    Args:
        vs_win: VS Code window control
        
    Returns:
        Tuple of (counts_dict, buttons_clicked_list)
        counts_dict has keys: 'allow', 'keep_edits', 'try_again', 'rate_limited'
    """
    from automation.ui.button_finder import find_all_allow_buttons_in_window
    from automation.rate_limit.tracker import record_allow_click
    from automation.panel_tracker import get_tracker
    
    counts = {'allow': 0, 'keep_edits': 0, 'try_again': 0, 'rate_limited': False}
    buttons_clicked: List[str] = []
    
    try:
        window_title = vs_win.Name or "Unknown"
    except Exception:
        window_title = "Unknown"
    
    if not ensure_window_focus(vs_win, description=window_title):
        counts['focus_failed'] = True
        return counts, buttons_clicked

    # Mark this panel as checked for Allow buttons (hourly tracking)
    try:
        tracker = get_tracker()
        tracker.mark_panel_allow_checked(window_title)
    except Exception:
        pass  # Don't fail if tracker isn't available

    if is_try_again_cooldown_active():
        remaining = get_try_again_cooldown_remaining()
        print(
            f"  [COOLDOWN] Skipping clicks in '{window_title}' – cooldown active"
            f" for another {remaining:.1f}s."
        )
        counts['rate_limited'] = True
        return counts, buttons_clicked
    
    # Find all action buttons (Allow, Keep, Try Again)
    buttons = find_all_allow_buttons_in_window(vs_win)

    if not buttons:
        try:
            win_title = vs_win.Name or "Unknown"
        except Exception:
            win_title = "Unknown"
        log_verbose(f"  [DEBUG] No action buttons found in window: {win_title}")
    
    for btn in buttons:
        from automation.core.hotkeys import check_hotkeys_polled, is_paused
        check_hotkeys_polled()
        if is_paused():
            print(f"  [PAUSE] Aborting clicks in '{window_title}' – automation paused.")
            break

        if is_try_again_cooldown_active():
            remaining = get_try_again_cooldown_remaining()
            print(
                f"  [COOLDOWN] Aborting further clicks in '{window_title}'"
                f" – cooldown has {remaining:.1f}s remaining."
            )
            counts['rate_limited'] = True
            break
        
        try:
            btn_name = btn.Name or ""
        except Exception:
            continue
        
        # Determine button type
        if btn_name in ("Allow", "Allow (Ctrl+Enter)", "Allow Everywhere"):
            btn_type = 'allow'
            description = f"{btn_name} button"
        elif btn_name.startswith("Keep") or "Keep Edits" in btn_name or "Keep Chat Edits" in btn_name:
            btn_type = 'keep_edits'
            description = f"{btn_name} button"
            if IGNORE_KEEP_BUTTONS:
                print(f"  [SKIP] IGNORE_KEEP_BUTTONS=true; skipping {btn_name} in {window_title}")
                continue
        elif btn_name.startswith("Try Again"):
            btn_type = 'try_again'
            description = "Try Again button"
        else:
            continue
        
        # Click the button
        if click_button_with_verification(btn, description):
            counts[btn_type] += 1
            _window_approval_stats[window_title][btn_type] += 1
            buttons_clicked.append(btn_name)
            
            if btn_type == 'allow':
                print(f"  ✓ Allow click counted in {window_title}")
                record_allow_click(window_title)
                
                # After Allow click, wait 2s to see if rate limit kicks in
                time.sleep(POST_ALLOW_CHECK_DELAY)
                
                if check_for_try_again_button(vs_win):
                    # Rate limited! Trigger cooldown and stop processing
                    trigger_rate_limit_cooldown(window_title)
                    counts['rate_limited'] = True
                    return counts, buttons_clicked
                    
            elif btn_type == 'keep_edits':
                print(f"  ✓ Keep Edits click counted in {window_title}")
                
            elif btn_type == 'try_again':
                print(f"  ✓ Try Again click counted in {window_title}")
                
                # After Try Again click, wait 2s to see if still rate limited
                time.sleep(POST_ALLOW_CHECK_DELAY)
                
                if check_for_try_again_button(vs_win):
                    # Still rate limited after retry! Trigger cooldown
                    trigger_rate_limit_cooldown(window_title)
                    counts['rate_limited'] = True
                    return counts, buttons_clicked
                else:
                    # Try Again worked - treat it like an Allow for tracking
                    print(f"  ✓ Retry succeeded (no new Try Again appeared)")
        else:
            # Debug: show verification failure
            if btn_type == 'allow':
                print(f"  ✗ Allow click NOT counted (verification failed)")
            elif btn_type == 'keep_edits':
                print(f"  ✗ Keep Edits click NOT counted (verification failed)")
            elif btn_type == 'try_again':
                print(f"  ✗ Try Again click NOT counted (verification failed)")
    
    if any(
        counts[key] > 0 for key in ('allow', 'keep_edits', 'try_again')
    ):
        print(
            f"  [WINDOW-STATS] {window_title}: {_window_approval_stats[window_title]}"
        )
    
    return counts, buttons_clicked
