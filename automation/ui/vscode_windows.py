"""
VS Code window detection and management.

Provides functions to find VS Code windows and manage their priority.
"""

from __future__ import annotations

from typing import List, TYPE_CHECKING

import uiautomation as auto

from automation.config import (
    VSCODE_TITLE_SUFFIX,
    WINDOW_PRIORITY_PATTERNS,
)

from automation.title_parsing import is_vscode_window_title

if TYPE_CHECKING:
    pass


def find_all_vscode_windows(timeout: float = 0.5) -> List[auto.Control]:
    """
    Find ALL VS Code windows by title suffix.
    
    Searches for windows ending with " - Visual Studio Code".
    Uses searchDepth=1 for speed (top-level windows only).
    
    Args:
        timeout: Timeout for Exists() check per window
        
    Returns:
        List of VS Code window Controls (WindowControl or PaneControl)
    """
    vscode_windows: List[auto.Control] = []
    
    try:
        for w in auto.GetRootControl().GetChildren():
            # VS Code can be WindowControl or PaneControl depending on state
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and is_vscode_window_title(name):
                        if w.Exists(timeout):
                            vscode_windows.append(w)
                except Exception:
                    continue
    except Exception as e:
        # Handle COM errors when UI elements become invalid during enumeration
        print(f"  ⚠️  Warning: UI enumeration error (likely transient): {e}")
    
    return vscode_windows


def get_window_priority(window: auto.Control) -> int:
    """
    Return a priority score for a VS Code window based on its title.
    
    Lower numbers = higher priority (processed first).
    
    Priority is determined by matching against WINDOW_PRIORITY_PATTERNS.
    First pattern match = priority 0, second = 1, etc.
    Non-matching windows get lowest priority.
    
    Args:
        window: VS Code window control
        
    Returns:
        Priority score (lower = higher priority)
    """
    try:
        title = (window.Name or "").lower()
        
        for priority_idx, pattern in enumerate(WINDOW_PRIORITY_PATTERNS):
            if pattern.lower() in title:
                return priority_idx
        
        return len(WINDOW_PRIORITY_PATTERNS)
    except Exception:
        return len(WINDOW_PRIORITY_PATTERNS)


def get_window_priority_with_panel_status(window: auto.Control) -> int:
    """
    Get priority score including panel tracking status.
    
    Priority layers:
    1. Panel status (live panels first, finished panels last)
    2. Title patterns (WINDOW_PRIORITY_PATTERNS)
    
    Args:
        window: VS Code window control
        
    Returns:
        Combined priority score
    """
    try:
        from automation.panel_tracker import get_window_priority as get_panel_priority
        
        title = (window.Name or "")
        
        # First priority layer: Panel status
        # Live panels get priority 0-99, Idle get 100-199, Finished get 200-299
        panel_priority = get_panel_priority(title) * 100
        
        # Second priority layer: Title pattern matching
        title_lower = title.lower()
        for priority_idx, pattern in enumerate(WINDOW_PRIORITY_PATTERNS):
            if pattern.lower() in title_lower:
                return panel_priority + priority_idx
        
        return panel_priority + len(WINDOW_PRIORITY_PATTERNS)
    except Exception:
        return len(WINDOW_PRIORITY_PATTERNS)


def is_live_panel_window(window: auto.Control) -> bool:
    """
    Check if a window contains a live (actively running or waiting for Allow) panel.
    
    Live panels are:
    - RUNNING: Cancel button visible, agent working
    - WAITING_ALLOW: Allow button visible, needs click
    - Unknown: Not yet tracked (assume live)
    
    Non-live panels (only check when idle):
    - IDLE: No activity recently
    - FINISHED: Output unchanged for 30+ min
    - COMPLETED: Agent said "task completed"
    - STALE: Not verified/scanned recently
    
    Args:
        window: VS Code window control
        
    Returns:
        True if this window should be prioritized for scanning
    """
    try:
        from automation.panel_tracker import get_tracker, PanelStatus
        
        title = (window.Name or "")
        tracker = get_tracker()
        key = tracker._generate_panel_key(title)
        
        if key not in tracker.panels:
            # Unknown panel - treat as live (needs scanning)
            return True
        
        panel = tracker.panels[key]
        
        # Live statuses that need immediate attention
        return panel.status in (
            PanelStatus.RUNNING,
            PanelStatus.WAITING_ALLOW,
            PanelStatus.RATE_LIMITED,
        )
    except Exception:
        # If anything fails, assume live to be safe
        return True


def partition_windows_by_priority(windows: List[auto.Control]) -> tuple:
    """
    Partition windows into live and idle/finished groups.
    
    Live windows: RUNNING, WAITING_ALLOW, RATE_LIMITED, or unknown
    Idle windows: IDLE, FINISHED, COMPLETED, STALE
    
    Args:
        windows: List of VS Code window controls
        
    Returns:
        Tuple of (live_windows, idle_windows), each sorted by priority
    """
    live_windows = []
    idle_windows = []
    
    for window in windows:
        if is_live_panel_window(window):
            live_windows.append(window)
        else:
            idle_windows.append(window)
    
    # Sort each group by priority
    live_windows = sorted(live_windows, key=get_window_priority_with_panel_status)
    idle_windows = sorted(idle_windows, key=get_window_priority_with_panel_status)
    
    return live_windows, idle_windows


def sort_windows_by_priority(windows: List[auto.Control]) -> List[auto.Control]:
    """
    Sort VS Code windows by priority based on WINDOW_PRIORITY_PATTERNS.
    
    TF windows first, then Trading, then others.
    
    Args:
        windows: List of VS Code window controls
        
    Returns:
        Sorted list (highest priority first)
    """
    if not WINDOW_PRIORITY_PATTERNS:
        return windows
    return sorted(windows, key=get_window_priority_with_panel_status)


def get_window_title(window: auto.Control) -> str:
    """
    Safely get window title.
    
    Args:
        window: Window control
        
    Returns:
        Window title or "Unknown"
    """
    try:
        return window.Name or "Unknown"
    except Exception:
        return "Unknown"


def get_window_handle(window: auto.Control) -> int:
    """
    Get the native window handle (HWND).
    
    Args:
        window: Window control
        
    Returns:
        Window handle or 0 if not available
    """
    try:
        return window.NativeWindowHandle or 0
    except Exception:
        return 0
