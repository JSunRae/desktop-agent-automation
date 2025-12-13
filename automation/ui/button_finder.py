"""
Button finding utilities for VS Code Copilot automation.

Finds various action buttons in VS Code windows:
- Allow (Ctrl+Enter) buttons for command confirmations
- Keep Edits buttons for accepting changes
- Try Again buttons for rate limit recovery
- Focus Terminal buttons that need attention
"""

from __future__ import annotations

import os
from typing import List, Optional, TYPE_CHECKING

import uiautomation as auto

from automation.config import (
    ALLOW_BUTTON_NAMES,
    KEEP_BUTTON_NAMES,
    ALL_ACTION_BUTTON_NAMES,
)

if TYPE_CHECKING:
    pass


# Control types that can be clicked
CLICKABLE_CONTROL_TYPES = [
    auto.ControlType.ButtonControl,
    auto.ControlType.SplitButtonControl,
    auto.ControlType.HyperlinkControl,
]


def _has_positive_bounds(control: auto.Control) -> bool:
    """Return True when UIA reports a rectangle with width/height."""
    try:
        rect = control.BoundingRectangle
        return (rect.right - rect.left) > 0 and (rect.bottom - rect.top) > 0
    except Exception:
        return False


def _is_clickable_control(control: auto.Control) -> bool:
    """Check whether the control type is something we can click."""
    try:
        return control.ControlType in CLICKABLE_CONTROL_TYPES
    except Exception:
        return False


def _control_identity(control: auto.Control) -> str:
    """Stable-ish key for deduplicating the same UIA element."""
    try:
        runtime_id = control.GetRuntimeId()
        if runtime_id:
            return "runtime:" + ".".join(str(v) for v in runtime_id)
    except Exception:
        pass
    try:
        handle = control.NativeWindowHandle
        if handle:
            return f"hwnd:{handle}"
    except Exception:
        pass
    return f"id:{id(control)}"


def _promote_to_clickable(control: auto.Control) -> Optional[auto.Control]:
    """Walk parents/children to locate a clickable wrapper for text-only hits."""
    candidates: List[auto.Control] = []

    if _is_clickable_control(control):
        candidates.append(control)

    parent: Optional[auto.Control] = control
    for _ in range(4):
        if not parent:
            break
        try:
            parent = parent.GetParentControl()
        except Exception:
            parent = None
        if not parent:
            break
        if _is_clickable_control(parent):
            candidates.append(parent)
            break

    try:
        for child in control.GetChildren():
            if _is_clickable_control(child):
                candidates.append(child)
                break
    except Exception:
        pass

    for candidate in candidates:
        if _has_positive_bounds(candidate):
            return candidate

    return candidates[0] if candidates else None

DEBUG_BUTTON_SCAN = os.environ.get("DEBUG_BUTTON_SCAN", "").lower() == "true"


# UIA sometimes leaves Name empty for Chromium-hosted controls.  Fall back to
# LegacyIAccessible when needed so we keep recognizing Allow buttons.
def _get_control_name(control: auto.Control) -> str:
    try:
        name = control.Name  # type: ignore[attr-defined]
        if name:
            return name
    except Exception:
        pass

    try:
        legacy = control.GetLegacyIAccessiblePattern()  # type: ignore[attr-defined]
        if legacy:
            try:
                name = legacy.Name
                if name:
                    return name
            except Exception:
                pass
            try:
                value = legacy.Value
                if value:
                    return value
            except Exception:
                pass
    except Exception:
        pass

    return ""


def find_all_allow_buttons_in_window(
    vs_win: auto.Control,
    max_depth: int = 70,
) -> List[auto.Control]:
    """
    Find all Allow, Keep, and action buttons in a VS Code window.
    
    Despite the name (kept for backwards compatibility), this function finds
    all action buttons including Allow, Keep, and Try Again buttons.
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth for UI tree search
        
    Returns:
        List of action button controls
    """
    found_buttons: List[auto.Control] = []
    seen_controls: set[str] = set()
    sample_clickable: List[str] = []  # names/types of clickable controls seen
    sample_named_controls: List[str] = []  # any control whose name hints at Allow/Keep/Try
    scanned = 0
    
    def search_recursive(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            nonlocal scanned
            scanned += 1
            name = _get_control_name(control)
            lowered = name.lower() if name else ""

            # Capture any interestingly named controls for diagnostics, regardless of type
            if name and any(k in lowered for k in ("allow", "approve", "keep", "try again")):
                if len(sample_named_controls) < 20:
                    try:
                        rect = control.BoundingRectangle
                        bounds = f"({rect.left},{rect.top},{rect.right},{rect.bottom})"
                    except Exception:
                        bounds = "(n/a)"
                    getter = getattr(control, "GetInvokePattern", None)
                    has_invoke = False
                    if callable(getter):
                        try:
                            has_invoke = bool(getter())
                        except Exception:
                            has_invoke = False
                    sample_named_controls.append(
                        f"{name} [{control.ControlType}] bounds={bounds} invoke={has_invoke} depth={depth}"
                    )

            # Check both Button and SplitButton control types
            if control.ControlType in CLICKABLE_CONTROL_TYPES:
                if len(sample_clickable) < 20:
                    try:
                        rect = control.BoundingRectangle
                        bounds = f"({rect.left},{rect.top},{rect.right},{rect.bottom})"
                    except Exception:
                        bounds = "(n/a)"
                    sample_clickable.append(f"{name or '<none>'} [{control.ControlType}] bounds={bounds} depth={depth}")

            # Broaden matching to catch variant labels like "Allow (Enter)" or "Approve"
            match_allow = (
                name in ALLOW_BUTTON_NAMES
                or (name and name.startswith("Allow"))
                or ("allow" in lowered)
                or ("approve" in lowered)
            )

            # Keep/Keep Edits variants often start with Keep
            match_keep = (
                name in KEEP_BUTTON_NAMES
                or (name and name.startswith("Keep"))
                or ("keep edits" in lowered)
            )

            match_try_again = name in ALL_ACTION_BUTTON_NAMES or (name and name.startswith("Try Again"))

            if match_allow or match_keep or match_try_again:
                if control.Exists(0.1):
                    clickable = _promote_to_clickable(control)
                    if clickable:
                        identity = _control_identity(clickable)
                        if identity not in seen_controls:
                            seen_controls.add(identity)
                            found_buttons.append(clickable)
            
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
        except Exception:
            pass
    
    search_recursive(vs_win)

    if not found_buttons and DEBUG_BUTTON_SCAN:
        print("[DEBUG] No action buttons matched. Scanned controls:", scanned)
        if sample_clickable:
            print("[DEBUG] Sample clickable controls:", sample_clickable)
        if sample_named_controls:
            print("[DEBUG] Named controls containing allow/approve/keep/try:", sample_named_controls)
    return found_buttons


def find_try_again_buttons(
    vs_win: auto.Control,
    max_depth: int = 50,
) -> List[auto.Control]:
    """
    Recursively search for "Try Again" buttons (rate limit recovery).
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth
        
    Returns:
        List of Try Again button controls
    """
    found_buttons: List[auto.Control] = []
    
    def search_recursive(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth:
            return
        
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name
                if name and "Try Again" in name:
                    if control.Exists(0.1):
                        found_buttons.append(control)
            
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found_buttons


def find_focus_terminal_buttons(
    vs_win: auto.Control,
    max_depth: int = 50,
) -> List[auto.Control]:
    """
    Recursively search for "Focus Terminal" buttons that require user attention.
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth
        
    Returns:
        List of Focus Terminal button controls
    """
    found_buttons: List[auto.Control] = []
    
    def search_recursive(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth:
            return
        
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name
                if name and "Focus Terminal" in name:
                    if control.Exists(0.1):
                        found_buttons.append(control)
            
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found_buttons


def find_all_action_buttons(
    vs_win: auto.Control,
    max_depth: int = 50,
) -> List[tuple]:
    """
    Find all action buttons (Allow, Keep Edits, Try Again) in a VS Code window.
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth
        
    Returns:
        List of (button_name, button_control) tuples
    """
    found: List[tuple] = []
    
    def search_recursive(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth:
            return
        
        try:
            # Check both Button and SplitButton control types
            if control.ControlType in CLICKABLE_CONTROL_TYPES:
                name = control.Name
                # Match exact names or "Try Again" prefix
                if name in ALL_ACTION_BUTTON_NAMES or (name and name.startswith("Try Again")):
                    found.append((name, control))
            
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found


def get_chat_confirmation_text(button: auto.Control) -> str:
    """
    Extract the chat confirmation text from the dialog containing the Allow button.
    
    Walks up the parent hierarchy to find the dialog group.
    
    Args:
        button: The Allow button control
        
    Returns:
        Extracted chat text or "Unable to extract chat text"
    """
    try:
        # Walk up to find the "Chat Confirmation Dialog" group
        parent = button.GetParentControl()
        depth = 0
        while parent and depth < 10:
            try:
                name = parent.Name
                if name and "Chat Confirmation Dialog" in name:
                    # Found the dialog, extract the text after "Chat Confirmation Dialog"
                    return name.replace("Chat Confirmation Dialog", "").strip()
                
                if name and "Chat confirmation required:" in name:
                    parts = name.split(":", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()[:100]
            except Exception:
                pass
            
            parent = parent.GetParentControl()
            depth += 1
    except Exception:
        pass
    
    return "Unable to extract chat text"


def categorize_button(button_name: str) -> str:
    """
    Categorize a button by its name.
    
    Args:
        button_name: Name of the button
        
    Returns:
        Category: "allow", "keep_edits", "try_again", or "unknown"
    """
    if button_name in ALLOW_BUTTON_NAMES:
        return "allow"
    elif button_name in KEEP_BUTTON_NAMES:
        return "keep_edits"
    elif button_name and button_name.startswith("Try Again"):
        return "try_again"
    else:
        return "unknown"
