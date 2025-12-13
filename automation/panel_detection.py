"""UI-level detection helpers for Copilot panels."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from automation.panel_state import IdleReason

if TYPE_CHECKING:
    import uiautomation as auto


def detect_panel_running_state(vs_win: "auto.Control") -> bool:
    """Return True when Cancel button is present (agent running)."""
    import uiautomation as auto

    found_cancel = False
    found_send = False

    def search_for_buttons(control: auto.Control, depth: int = 0, max_depth: int = 50) -> None:
        nonlocal found_cancel, found_send
        if depth > max_depth:
            return
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name or ""
                if "Cancel" in name and ("Alt+Backspace" in name or "Backspace" in name):
                    if control.Exists(0.1):
                        found_cancel = True
                        return
                if "Send" in name and "Cancel" not in name:
                    if control.Exists(0.1):
                        found_send = True

            if found_cancel:
                return

            for child in control.GetChildren():
                search_for_buttons(child, depth + 1, max_depth)
                if found_cancel:
                    return
        except Exception:
            return

    search_for_buttons(vs_win)
    if found_cancel:
        return True
    if found_send:
        return False
    return False


def detect_panel_state_detailed(vs_win: "auto.Control") -> dict:
    """Return detailed state detection results."""
    import uiautomation as auto

    state = {
        "is_running": False,
        "has_send_button": False,
        "has_chat_panel": False,
    }

    def search_for_buttons(control: auto.Control, depth: int = 0, max_depth: int = 50) -> None:
        if depth > max_depth:
            return
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name or ""
                if "Cancel" in name and ("Alt+Backspace" in name or "Backspace" in name):
                    if control.Exists(0.1):
                        state["is_running"] = True
                        state["has_chat_panel"] = True
                        return
                if "Send" in name and "Cancel" not in name:
                    if control.Exists(0.1):
                        state["has_send_button"] = True
                        state["has_chat_panel"] = True

            if state["is_running"]:
                return

            for child in control.GetChildren():
                search_for_buttons(child, depth + 1, max_depth)
                if state["is_running"]:
                    return
        except Exception:
            return

    search_for_buttons(vs_win)
    return state


def detect_idle_reason(vs_win: "auto.Control") -> Optional[IdleReason]:
    """Determine why a panel is idle when Send is visible."""
    import uiautomation as auto

    found = {
        "allow": False,
        "try_again": False,
        "rate_limit_text": False,
    }

    rate_limit_patterns = [
        "rate-limited",
        "rate limited",
        "rate_limited",
        "exceeded your copilot token",
        "too many requests",
    ]

    def search_for_idle_indicators(control: auto.Control, depth: int = 0, max_depth: int = 50) -> None:
        if depth > max_depth:
            return
        try:
            name = control.Name or ""
            name_lower = name.lower()

            if isinstance(control, auto.ButtonControl):
                if "Allow" in name:
                    if control.Exists(0.1):
                        found["allow"] = True
                        return
                if "Try Again" in name:
                    if control.Exists(0.1):
                        found["try_again"] = True

            if name and len(name) > 20:
                for pattern in rate_limit_patterns:
                    if pattern in name_lower:
                        found["rate_limit_text"] = True
                        break

            if found["allow"]:
                return

            for child in control.GetChildren():
                search_for_idle_indicators(child, depth + 1, max_depth)
                if found["allow"]:
                    return
        except Exception:
            return

    search_for_idle_indicators(vs_win)

    if found["allow"]:
        return IdleReason.WAITING_ALLOW
    if found["try_again"]:
        return IdleReason.RATE_LIMITED_BUTTON
    if found["rate_limit_text"]:
        return IdleReason.RATE_LIMITED_NO_BUTTON
    return IdleReason.POSSIBLY_FINISHED


def get_comprehensive_panel_state(vs_win: "auto.Control") -> dict:
    """Combine running detection with idle reason detection."""
    state = detect_panel_state_detailed(vs_win)

    result = {
        "is_running": state["is_running"],
        "has_chat_panel": state["has_chat_panel"],
        "has_send_button": state["has_send_button"],
        "idle_reason": None,
        "needs_action": False,
    }

    if not state["is_running"] and state["has_chat_panel"]:
        result["idle_reason"] = detect_idle_reason(vs_win)
        if result["idle_reason"] in (
            IdleReason.WAITING_ALLOW,
            IdleReason.RATE_LIMITED_BUTTON,
            IdleReason.RATE_LIMITED_NO_BUTTON,
        ):
            result["needs_action"] = True

    return result
