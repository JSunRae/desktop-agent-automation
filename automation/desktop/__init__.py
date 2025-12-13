"""Desktop management - switching, caching, reliability tracking."""

from automation.desktop.switcher import (
    switch_to_desktop,
    detect_desktops_with_vscode,
    get_current_desktop,
    is_desktop_sync_done,
    reset_desktop_sync,
    needs_desktop_switch,
    get_desktops_to_check,
)
from automation.desktop.window_cache import (
    get_cached_vscode_windows,
    refresh_window_cache,
    should_refresh_cache,
    invalidate_cache,
)
from automation.desktop.reliability import (
    should_skip_desktop,
    record_desktop_result,
    increment_desktop_cycles,
    reset_all_desktop_failures,
    get_failure_count,
    get_cycles_since_check,
)

__all__ = [
    # Switcher
    "switch_to_desktop",
    "detect_desktops_with_vscode",
    "get_current_desktop",
    "is_desktop_sync_done",
    "reset_desktop_sync",
    "needs_desktop_switch",
    "get_desktops_to_check",
    # Cache
    "get_cached_vscode_windows",
    "refresh_window_cache",
    "should_refresh_cache",
    "invalidate_cache",
    # Reliability
    "should_skip_desktop",
    "record_desktop_result",
    "increment_desktop_cycles",
    "reset_all_desktop_failures",
    "get_failure_count",
    "get_cycles_since_check",
]
