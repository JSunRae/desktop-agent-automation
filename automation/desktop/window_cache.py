"""
Window handle caching for VS Code windows.

Instead of switching desktops every scan cycle, we can:
1. Scan all desktops ONCE to discover windows and cache their handles
2. Use ControlFromHandle to access windows directly (works across desktops!)
3. Only refresh the cache periodically to find new windows

This dramatically improves scan speed by eliminating desktop switching delays.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    import uiautomation as auto

from automation.config import (
    CACHE_REFRESH_INTERVAL_MINUTES,
    CACHE_STALE_THRESHOLD_MINUTES,
    VSCODE_TITLE_SUFFIX,
)
from automation.core.logging import log_verbose

from automation.title_parsing import is_vscode_window_title


# ============================================================================
# GLOBAL CACHE STATE
# ============================================================================

# Key: window handle (HWND), Value: (window_title, last_seen_time, desktop_id)
_cached_window_handles: Dict[int, Tuple[str, datetime, Union[int, str]]] = {}
_cache_initialized: bool = False
_last_cache_refresh: datetime = datetime.min


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def invalidate_cache() -> None:
    """Clear the window cache, forcing a refresh on next use."""
    global _cached_window_handles, _cache_initialized, _last_cache_refresh
    _cached_window_handles.clear()
    _cache_initialized = False
    _last_cache_refresh = datetime.min


def _prune_stale_handles(now: Optional[datetime] = None) -> None:
    """Remove cached window handles that haven't been seen recently."""
    now = now or datetime.now()
    stale_cutoff = now - timedelta(minutes=CACHE_STALE_THRESHOLD_MINUTES)
    
    stale_keys = [
        hwnd for hwnd, (_, last_seen, _) in _cached_window_handles.items()
        if last_seen < stale_cutoff
    ]
    
    for hwnd in stale_keys:
        title, _, desktop = _cached_window_handles.pop(hwnd, ("", datetime.min, 0))
        log_verbose(f"  [CACHE] Removed stale handle: {title[:40]}... (desktop {desktop})")


def should_refresh_cache(now: Optional[datetime] = None) -> bool:
    """Check if the window cache should be refreshed."""
    global _cache_initialized, _last_cache_refresh
    
    if not _cache_initialized:
        return True
    
    now = now or datetime.now()
    mins_since_refresh = (now - _last_cache_refresh).total_seconds() / 60
    return mins_since_refresh >= CACHE_REFRESH_INTERVAL_MINUTES


def refresh_window_cache(desktops: List[Union[int, str]], force: bool = False) -> int:
    """
    Scan all configured desktops and cache window handles.
    
    This is the ONE time we switch between desktops - to discover all windows.
    After this, we use the cached handles directly.
    
    Args:
        desktops: List of desktop names or numbers to scan
        force: If True, scan even if cache was recently refreshed
        
    Returns:
        Number of windows cached
    """
    global _cached_window_handles, _cache_initialized, _last_cache_refresh
    
    # Import here to avoid circular dependency
    from automation.desktop.switcher import switch_to_desktop
    from automation.ui.vscode_windows import find_all_vscode_windows
    
    now = datetime.now()
    
    # Skip if recently refreshed (unless forced)
    if not force and _cache_initialized:
        mins_since_refresh = (now - _last_cache_refresh).total_seconds() / 60
        if mins_since_refresh < CACHE_REFRESH_INTERVAL_MINUTES:
            return len(_cached_window_handles)
    
    print(f"\n[{now}] 📋 Scanning desktops to cache window handles...")
    
    # Prune stale entries first
    _prune_stale_handles(now)
    
    new_windows = 0
    updated_windows = 0
    
    for desktop_num in desktops:
        if desktop_num == 0:
            # Current desktop - no switch needed
            vscode_windows = find_all_vscode_windows(timeout=0.5)
        else:
            # Switch to desktop and scan
            switch_to_desktop(desktop_num)
            time.sleep(1.0)
            vscode_windows = find_all_vscode_windows(timeout=0.5)
        
        for vs_win in vscode_windows:
            try:
                hwnd = vs_win.NativeWindowHandle
                title = vs_win.Name or "Unknown"
                
                if hwnd:
                    if hwnd in _cached_window_handles:
                        # Update existing entry
                        _cached_window_handles[hwnd] = (title, now, desktop_num)
                        updated_windows += 1
                    else:
                        # New window
                        _cached_window_handles[hwnd] = (title, now, desktop_num)
                        new_windows += 1
                        desktop_label = "current" if desktop_num == 0 else f"desktop {desktop_num}"
                        log_verbose(f"  [CACHE] Found: {title[:50]}... ({desktop_label})")
            except Exception:
                continue
    
    _cache_initialized = True
    _last_cache_refresh = now
    
    total = len(_cached_window_handles)
    print(f"[{now}] ✓ Cache: {total} window(s) ({new_windows} new, {updated_windows} updated)")
    
    return total


def get_cached_vscode_windows() -> List["auto.Control"]:
    """
    Get VS Code windows from cache without switching desktops.
    
    Uses ControlFromHandle to get fresh Control objects from cached handles.
    Windows that no longer exist are automatically removed from cache.
    
    Returns:
        List of VS Code window controls
    """
    import uiautomation as auto
    
    now = datetime.now()
    windows: List[auto.Control] = []
    invalid_handles: List[int] = []
    
    for hwnd, (title, last_seen, desktop) in list(_cached_window_handles.items()):
        try:
            # Get control from handle - this works across virtual desktops!
            ctrl = auto.ControlFromHandle(hwnd)
            
            if ctrl and ctrl.Exists(0.2):
                # Verify it's still a VS Code window
                name = ctrl.Name or ""
                if is_vscode_window_title(name):
                    windows.append(ctrl)
                    # Update last seen time
                    _cached_window_handles[hwnd] = (name, now, desktop)
                else:
                    # Window changed (no longer VS Code)
                    invalid_handles.append(hwnd)
            else:
                # Window no longer exists
                invalid_handles.append(hwnd)
        except Exception:
            # Handle invalid
            invalid_handles.append(hwnd)
    
    # Remove invalid handles
    for hwnd in invalid_handles:
        if hwnd in _cached_window_handles:
            title, _, desktop = _cached_window_handles.pop(hwnd)
            log_verbose(f"  [CACHE] Removed invalid: {title[:40]}...")
    
    return windows


def get_desktop_for_handle(hwnd: int) -> Union[int, str, None]:
    """
    Get the desktop ID for a cached window handle.
    
    Args:
        hwnd: Window handle
        
    Returns:
        Desktop ID (int or str) or None if not found
    """
    if hwnd in _cached_window_handles:
        return _cached_window_handles[hwnd][2]
    return None


def get_cache_stats() -> Dict[str, int]:
    """Get statistics about the window cache."""
    return {
        "total_cached": len(_cached_window_handles),
        "initialized": _cache_initialized,
        "minutes_since_refresh": int(
            (datetime.now() - _last_cache_refresh).total_seconds() / 60
        ) if _cache_initialized else -1,
    }
