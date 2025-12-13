"""
Scrolling utilities for VS Code chat panels.

Provides functions to scroll chat panels and bring controls into view,
which is necessary for:
- Revealing hidden Allow buttons at the bottom of long chats
- Handling virtualized controls that don't render until scrolled into view
"""

from __future__ import annotations

import time
from typing import List, Optional, TYPE_CHECKING

import uiautomation as auto

from automation.ui.window_utils import (
    get_cursor_pos,
    set_cursor_pos,
    get_foreground_window,
    set_foreground_window,
)

if TYPE_CHECKING:
    pass


def scroll_control_into_view(control: auto.Control) -> bool:
    """
    Try to scroll a virtualized control into view via the ScrollItem pattern.
    
    Args:
        control: The control to scroll into view
        
    Returns:
        True if scroll was attempted
    """
    try:
        getter = getattr(control, "GetScrollItemPattern", None)
        if callable(getter):
            pattern = getter()
            if pattern:
                pattern.ScrollIntoView()
                time.sleep(0.05)
                return True
    except Exception:
        pass
    return False


def _find_chat_controls(vs_win: auto.Control, max_depth: int = 45) -> List[auto.Control]:
    """Find chat-related controls in a VS Code window."""
    matches: List[auto.Control] = []
    target_keywords = {"chat", "inline chat", "chat list", "chat messages"}

    def search(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth or len(matches) >= 6:
            return
        try:
            name = (control.Name or "").strip().lower()
            if name:
                if any(keyword in name for keyword in target_keywords):
                    if isinstance(
                        control,
                        (
                            auto.ListControl,
                            auto.PaneControl,
                            auto.DocumentControl,
                            auto.GroupControl,
                        ),
                    ):
                        matches.append(control)

            for child in control.GetChildren():
                search(child, depth + 1)
        except KeyboardInterrupt:
            raise
        except Exception:
            return

    search(vs_win)
    return matches


def _focus_control(ctrl: auto.Control) -> bool:
    """Try to focus a control for scrolling."""
    try:
        if not ctrl.Exists(0.2):
            return False
        try:
            ctrl.SetFocus()
            return True
        except Exception:
            rect = ctrl.BoundingRectangle
            if rect.left == rect.right and rect.top == rect.bottom:
                return False
            center_x = (rect.left + rect.right) // 2
            center_y = (rect.top + rect.bottom) // 2
            set_cursor_pos(center_x, center_y)
            time.sleep(0.02)
            ctrl.Click(simulateMove=False)
            return True
    except Exception:
        return False


def scroll_chat_to_bottom(vs_win: auto.Control) -> bool:
    """
    Try to scroll the chat panel to the bottom to reveal hidden Allow buttons.
    
    Uses keyboard shortcuts which are more reliable than UI Automation scroll methods.
    Preserves both mouse position and active window focus.
    
    Args:
        vs_win: VS Code window control
        
    Returns:
        True if scrolling was attempted
    """
    original_pos = get_cursor_pos()
    original_window = get_foreground_window()

    try:
        candidates = _find_chat_controls(vs_win)
        if not candidates:
            candidates = [vs_win]

        for ctrl in candidates:
            if not _focus_control(ctrl):
                continue

            time.sleep(0.05)
            for _ in range(3):
                auto.SendKeys('{Ctrl}{End}')
                time.sleep(0.08)
            auto.SendKeys('{Ctrl}{Down}')
            time.sleep(0.05)
            return True
    except Exception:
        return False
    finally:
        set_cursor_pos(original_pos[0], original_pos[1])
        if original_window:
            time.sleep(0.02)
            set_foreground_window(original_window)

    return False


def try_scroll_and_check_bounds(
    control: auto.Control,
    vs_win: Optional[auto.Control] = None,
) -> bool:
    """
    Attempt to scroll a control into view and return True if it now has valid bounds.
    
    This helps with virtualized controls (like buttons in scrolled chat panels)
    that report zero bounds because they're not currently rendered.
    
    Args:
        control: The control to scroll into view
        vs_win: Optional parent VS Code window for chat-level scrolling
        
    Returns:
        True if control now has valid bounds
    """
    from automation.ui.button_clicker import has_valid_bounds
    
    # First, try the control's own ScrollItem pattern
    if scroll_control_into_view(control):
        time.sleep(0.1)
        if has_valid_bounds(control):
            return True
    
    # If we have the VS Code window, try scrolling the chat to bottom
    if vs_win is not None:
        try:
            scroll_chat_to_bottom(vs_win)
            time.sleep(0.15)
            if has_valid_bounds(control):
                return True
        except Exception:
            pass
    
    # Last resort: Try to focus the control and send scroll keys
    try:
        parent = control.GetParentControl()
        if parent:
            parent.SetFocus()
            time.sleep(0.05)
            auto.SendKeys('{End}')
            time.sleep(0.1)
            if has_valid_bounds(control):
                return True
            auto.SendKeys('{Ctrl}{End}')
            time.sleep(0.1)
            if has_valid_bounds(control):
                return True
    except Exception:
        pass
    
    return False
