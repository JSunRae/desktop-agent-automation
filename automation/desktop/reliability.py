"""
Desktop reliability tracking.

Tracks consecutive failures per desktop to avoid wasting time on
desktops that consistently show no windows (possibly unreachable).

Features:
- Skip desktops after N consecutive "no windows" cycles
- Re-check failed desktops periodically
- Reset all failures when major state changes occur
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict

from automation.config import (
    DESKTOP_MAX_CONSECUTIVE_FAILURES,
    DESKTOP_RECHECK_AFTER_FAILURES,
)


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Track consecutive failures per desktop
# Key: desktop_num, Value: consecutive failure count
_desktop_failure_counts: Dict[int, int] = {}

# Track cycles since last check for failed desktops
# Key: desktop_num, Value: cycles since last check
_desktop_cycles_since_check: Dict[int, int] = {}


# ============================================================================
# PUBLIC API
# ============================================================================

def should_skip_desktop(desktop_num: int) -> bool:
    """
    Check if a desktop should be skipped due to consecutive failures.
    
    Args:
        desktop_num: The desktop number to check
        
    Returns:
        True if the desktop should be skipped, False otherwise
    """
    if DESKTOP_MAX_CONSECUTIVE_FAILURES <= 0:
        return False  # Tracking disabled

    failures = _desktop_failure_counts.get(desktop_num, 0)
    if failures >= DESKTOP_MAX_CONSECUTIVE_FAILURES:
        # Check if it's time to re-check this desktop
        cycles_since = _desktop_cycles_since_check.get(desktop_num, 0)
        if cycles_since >= DESKTOP_RECHECK_AFTER_FAILURES:
            # Time to re-check
            return False
        return True
    return False


def record_desktop_result(desktop_num: int, found_windows: bool) -> None:
    """
    Record whether we found windows on a desktop.
    
    Args:
        desktop_num: The desktop number
        found_windows: True if VS Code windows were found
    """
    if found_windows:
        # Reset failure count on success
        _desktop_failure_counts[desktop_num] = 0
        _desktop_cycles_since_check[desktop_num] = 0
    else:
        # Increment failure count
        _desktop_failure_counts[desktop_num] = _desktop_failure_counts.get(desktop_num, 0) + 1
        _desktop_cycles_since_check[desktop_num] = 0


def increment_desktop_cycles() -> None:
    """Increment cycles counter for all tracked desktops."""
    for desktop_num in list(_desktop_cycles_since_check.keys()):
        _desktop_cycles_since_check[desktop_num] = _desktop_cycles_since_check.get(desktop_num, 0) + 1


def reset_all_desktop_failures() -> None:
    """Reset all desktop failure counters to force re-checking all desktops."""
    global _desktop_failure_counts, _desktop_cycles_since_check
    _desktop_failure_counts.clear()
    _desktop_cycles_since_check.clear()
    print(f"[{datetime.now()}] 🔄 Reset all desktop failure counters - will recheck all desktops")


def get_failure_count(desktop_num: int) -> int:
    """Get the current failure count for a desktop."""
    return _desktop_failure_counts.get(desktop_num, 0)


def get_cycles_since_check(desktop_num: int) -> int:
    """Get cycles since last check for a desktop."""
    return _desktop_cycles_since_check.get(desktop_num, 0)


def get_all_failure_stats() -> Dict[int, Dict[str, int]]:
    """Get failure statistics for all tracked desktops."""
    result: Dict[int, Dict[str, int]] = {}
    all_desktops = set(_desktop_failure_counts.keys()) | set(_desktop_cycles_since_check.keys())
    
    for desktop_num in all_desktops:
        result[desktop_num] = {
            "failures": _desktop_failure_counts.get(desktop_num, 0),
            "cycles_since_check": _desktop_cycles_since_check.get(desktop_num, 0),
        }
    
    return result
