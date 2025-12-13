"""
Allow event tracking for rate limit management.

Tracks Allow button clicks in a rolling time window to:
- Prevent exceeding rate limits
- Provide wait time estimates
- Persist state across restarts
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Tuple, Optional

from automation.config import (
    MAX_ALLOWS_PER_HOUR,
    RATE_LIMIT_BUFFER_SECONDS,
    ALLOW_EVENT_RETENTION_MINUTES,
    ALLOW_EVENTS_PERSIST_PATH,
)


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Deque of (timestamp, window_title) for recent Allow clicks
_allow_events: Deque[Tuple[datetime, str]] = deque()

# Total Allow clicks this session
_allow_click_total: int = 0

# Last Allow click time (for idle detection)
_last_allow_time: datetime = datetime.now()

# Whether we've recorded at least one Allow click
_has_recorded_allow: bool = False


# ============================================================================
# PUBLIC API
# ============================================================================

def record_allow_click(window_title: str) -> None:
    """
    Store the timestamp + window title for an Allow action.
    
    Args:
        window_title: Title of the VS Code window where Allow was clicked
    """
    global _last_allow_time, _allow_click_total, _has_recorded_allow
    
    now = datetime.now()
    _allow_events.append((now, window_title or "Unknown"))
    _last_allow_time = now
    _allow_click_total += 1
    _has_recorded_allow = True
    prune_allow_events(now)
    save_allow_events()
    
    # Track panel for idle/finished monitoring
    try:
        from automation.panel_tracker import on_allow_click
        on_allow_click(window_title)
    except ImportError:
        pass


def prune_allow_events(reference_time: Optional[datetime] = None) -> None:
    """
    Drop allow-click records that fall outside the retention window.
    
    Args:
        reference_time: Current time (defaults to now)
    """
    reference_time = reference_time or datetime.now()
    cutoff = reference_time - timedelta(minutes=ALLOW_EVENT_RETENTION_MINUTES)
    while _allow_events and _allow_events[0][0] < cutoff:
        _allow_events.popleft()


def can_click_allow(now: Optional[datetime] = None) -> bool:
    """
    Check if we're under the rate limit and can click Allow buttons.
    
    Args:
        now: Current time (defaults to now)
        
    Returns:
        True if clicking is allowed
    """
    return get_rate_limit_wait_seconds(now) <= 0


def get_rate_limit_wait_seconds(now: Optional[datetime] = None) -> float:
    """
    Calculate how long to wait before the next Allow click is permitted.
    
    Returns:
        0 if we're under the rate limit and can click immediately.
        Positive seconds if we need to wait for the oldest event to expire.
    """
    now = now or datetime.now()
    prune_allow_events(now)
    
    current_count = len(_allow_events)
    
    if current_count < MAX_ALLOWS_PER_HOUR:
        return 0.0  # Under limit, can click immediately
    
    # At or over limit - calculate when the oldest event will expire
    if not _allow_events:
        return 0.0
    
    oldest_event_time = _allow_events[0][0]
    expiry_time = oldest_event_time + timedelta(minutes=ALLOW_EVENT_RETENTION_MINUTES)
    wait_seconds = (expiry_time - now).total_seconds() + RATE_LIMIT_BUFFER_SECONDS
    
    return max(0.0, wait_seconds)


def format_rate_status(now: Optional[datetime] = None) -> str:
    """
    Return a human-readable rate limit status string.
    
    Args:
        now: Current time (defaults to now)
        
    Returns:
        String like "45/70 allows in last 60min"
    """
    now = now or datetime.now()
    prune_allow_events(now)
    current_count = len(_allow_events)
    return f"{current_count}/{MAX_ALLOWS_PER_HOUR} allows in last 60min"


def get_allow_event_count() -> int:
    """Get the number of Allow events in the current window."""
    prune_allow_events()
    return len(_allow_events)


def get_last_allow_time() -> datetime:
    """Get the timestamp of the last Allow click."""
    return _last_allow_time


def get_total_allow_clicks() -> int:
    """Get total Allow clicks this session."""
    return _allow_click_total


def has_recorded_allow() -> bool:
    """Check if at least one Allow has been clicked this session."""
    return _has_recorded_allow


# ============================================================================
# PERSISTENCE
# ============================================================================

def load_allow_events() -> None:
    """Load persisted allow events from disk on startup."""
    global _allow_events, _last_allow_time, _allow_click_total, _has_recorded_allow
    
    if not ALLOW_EVENTS_PERSIST_PATH.exists():
        return
    
    try:
        with ALLOW_EVENTS_PERSIST_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        now = datetime.now()
        cutoff = now - timedelta(minutes=ALLOW_EVENT_RETENTION_MINUTES)
        loaded_count = 0
        
        for event in data.get("events", []):
            try:
                event_time = datetime.fromisoformat(event["timestamp"])
                if event_time > cutoff:
                    _allow_events.append((event_time, event.get("window", "Unknown")))
                    loaded_count += 1
            except (ValueError, KeyError):
                continue
        
        if loaded_count > 0:
            _last_allow_time = _allow_events[-1][0]
            _has_recorded_allow = True
            print(f"[{now}] Loaded {loaded_count} allow events from previous session ({len(_allow_events)}/{MAX_ALLOWS_PER_HOUR} in last 60min)")
    except Exception as e:
        print(f"[{datetime.now()}] Warning: Could not load persisted allow events: {e}")


def save_allow_events() -> None:
    """Save current allow events to disk for persistence across restarts."""
    try:
        ALLOW_EVENTS_PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        events_data = {
            "saved_at": datetime.now().isoformat(),
            "retention_minutes": ALLOW_EVENT_RETENTION_MINUTES,
            "events": [
                {"timestamp": ts.isoformat(), "window": title}
                for ts, title in _allow_events
            ]
        }
        
        with ALLOW_EVENTS_PERSIST_PATH.open("w", encoding="utf-8") as f:
            json.dump(events_data, f, indent=2)
    except Exception as e:
        print(f"[{datetime.now()}] Warning: Could not save allow events: {e}")


# ============================================================================
# METRICS SNAPSHOT
# ============================================================================

def get_metrics_snapshot(now: Optional[datetime] = None) -> dict:
    """
    Get a snapshot of current Allow metrics for logging.
    
    Args:
        now: Current time (defaults to now)
        
    Returns:
        Dict with metrics data
    """
    now = now or datetime.now()
    prune_allow_events(now)
    panels = {title for _, title in _allow_events}
    return {
        "allows_last_window": len(_allow_events),
        "panels_last_window": len(panels),
        "last_allow_time": _last_allow_time.isoformat() if _allow_events else None,
        "total_allow_clicks": _allow_click_total,
    }
