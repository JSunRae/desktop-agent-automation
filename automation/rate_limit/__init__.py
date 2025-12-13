"""Rate limit management - tracking, detection, cooldown handling."""

from automation.rate_limit.tracker import (
    record_allow_click,
    can_click_allow,
    get_rate_limit_wait_seconds,
    prune_allow_events,
    format_rate_status,
    get_allow_event_count,
    load_allow_events,
    save_allow_events,
)
from automation.rate_limit.detector import (
    detect_rate_limit_in_window,
    find_rate_limit_text_panels,
)
from automation.rate_limit.cooldown import (
    is_in_cooldown,
    start_cooldown,
    get_cooldown_remaining,
    is_in_grace_period,
)

__all__ = [
    # Tracker
    "record_allow_click",
    "can_click_allow",
    "get_rate_limit_wait_seconds",
    "prune_allow_events",
    "format_rate_status",
    "get_allow_event_count",
    "load_allow_events",
    "save_allow_events",
    # Detector
    "detect_rate_limit_in_window",
    "find_rate_limit_text_panels",
    # Cooldown
    "is_in_cooldown",
    "start_cooldown",
    "get_cooldown_remaining",
    "is_in_grace_period",
]
