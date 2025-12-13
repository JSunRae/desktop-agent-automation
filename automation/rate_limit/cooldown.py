"""
Cooldown management for rate limit recovery.

Manages the cooldown period after rate limit detection:
- Tracks cooldown end time
- Manages grace period for ignoring pre-existing rate limits
- Provides status queries
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Set

from automation.config import (
    COOLDOWN_MINUTES,
    POST_COOLDOWN_GRACE_MINUTES,
)


# ============================================================================
# GLOBAL STATE
# ============================================================================

# When the current cooldown ends
_next_allowed_check: datetime = datetime.min

# When grace period expires (ignoring old rate limit indicators)
_grace_period_end: datetime = datetime.min

# Window titles that had rate limits before cooldown (to ignore during grace period)
_pre_cooldown_fingerprints: Set[str] = set()


# ============================================================================
# COOLDOWN MANAGEMENT
# ============================================================================

def start_cooldown(
    trigger_time: Optional[datetime] = None,
    affected_windows: Optional[Set[str]] = None,
) -> datetime:
    """
    Start a cooldown period after rate limit detection.
    
    Args:
        trigger_time: When the rate limit was detected (defaults to now)
        affected_windows: Window titles that had rate limits
        
    Returns:
        When the cooldown will end
    """
    global _next_allowed_check, _pre_cooldown_fingerprints
    
    trigger_time = trigger_time or datetime.now()
    _next_allowed_check = trigger_time + timedelta(minutes=COOLDOWN_MINUTES)
    
    if affected_windows:
        _pre_cooldown_fingerprints = affected_windows.copy()
    else:
        _pre_cooldown_fingerprints = set()
    
    return _next_allowed_check


def end_cooldown() -> None:
    """End the cooldown and start the grace period."""
    global _grace_period_end, _next_allowed_check
    
    _next_allowed_check = datetime.min
    _grace_period_end = datetime.now() + timedelta(minutes=POST_COOLDOWN_GRACE_MINUTES)


def is_in_cooldown(now: Optional[datetime] = None) -> bool:
    """
    Check if we're currently in a cooldown period.
    
    Args:
        now: Current time (defaults to now)
        
    Returns:
        True if in cooldown
    """
    now = now or datetime.now()
    return now < _next_allowed_check


def get_cooldown_remaining(now: Optional[datetime] = None) -> float:
    """
    Get seconds remaining in cooldown.
    
    Args:
        now: Current time (defaults to now)
        
    Returns:
        Seconds remaining (0 if not in cooldown)
    """
    now = now or datetime.now()
    if now >= _next_allowed_check:
        return 0.0
    return (_next_allowed_check - now).total_seconds()


def get_cooldown_end() -> datetime:
    """Get when the current cooldown ends."""
    return _next_allowed_check


def set_cooldown_end(end_time: datetime) -> None:
    """Set the cooldown end time directly."""
    global _next_allowed_check
    _next_allowed_check = end_time


# ============================================================================
# GRACE PERIOD MANAGEMENT
# ============================================================================

def is_in_grace_period(now: Optional[datetime] = None) -> bool:
    """
    Check if we're in the grace period after cooldown.
    
    During grace period, we ignore rate limit indicators from windows
    that were already showing rate limits before the cooldown.
    
    Args:
        now: Current time (defaults to now)
        
    Returns:
        True if in grace period
    """
    now = now or datetime.now()
    return now < _grace_period_end


def should_ignore_window_rate_limit(window_title: str, now: Optional[datetime] = None) -> bool:
    """
    Check if rate limit in a window should be ignored (during grace period).
    
    Args:
        window_title: Window title to check
        now: Current time (defaults to now)
        
    Returns:
        True if this window's rate limit should be ignored
    """
    if not is_in_grace_period(now):
        return False
    
    return window_title in _pre_cooldown_fingerprints


def get_pre_cooldown_fingerprints() -> Set[str]:
    """Get the set of windows that had rate limits before cooldown."""
    return _pre_cooldown_fingerprints.copy()


def clear_grace_period() -> None:
    """Clear grace period state."""
    global _grace_period_end, _pre_cooldown_fingerprints
    _grace_period_end = datetime.min
    _pre_cooldown_fingerprints = set()
