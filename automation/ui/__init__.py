"""UI automation utilities - window finding, clicking, scrolling."""

from automation.ui.window_utils import (
    get_cursor_pos,
    set_cursor_pos,
    get_foreground_window,
    set_foreground_window,
    get_system_idle_seconds,
)
from automation.ui.vscode_windows import (
    find_all_vscode_windows,
    get_window_priority,
    sort_windows_by_priority,
    is_live_panel_window,
    partition_windows_by_priority,
)
from automation.ui.button_finder import (
    find_all_allow_buttons_in_window,
    find_try_again_buttons,
    find_focus_terminal_buttons,
)
from automation.ui.button_clicker import (
    click_button_instantly,
    click_button_with_verification,
    click_all_action_buttons,
    is_try_again_cooldown_active,
    get_try_again_cooldown_remaining,
    get_try_again_count_in_window,
)
from automation.ui.toast_watcher import try_consume_vscode_toast
from automation.ui.scroll import (
    scroll_chat_to_bottom,
    scroll_control_into_view,
)

__all__ = [
    # Window utils
    "get_cursor_pos",
    "set_cursor_pos",
    "get_foreground_window",
    "set_foreground_window",
    "get_system_idle_seconds",
    # VS Code windows
    "find_all_vscode_windows",
    "get_window_priority",
    "sort_windows_by_priority",
    "is_live_panel_window",
    "partition_windows_by_priority",
    # Button finder
    "find_all_allow_buttons_in_window",
    "find_try_again_buttons",
    "find_focus_terminal_buttons",
    # Button clicker
    "click_button_instantly",
    "click_button_with_verification",
    "click_all_action_buttons",
    "is_try_again_cooldown_active",
    "get_try_again_cooldown_remaining",
    "get_try_again_count_in_window",
    # Toasts
    "try_consume_vscode_toast",
    # Scroll
    "scroll_chat_to_bottom",
    "scroll_control_into_view",
]
