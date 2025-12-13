"""Core automation utilities - audio, logging, hotkeys, session tracking."""

from automation.core.audio import beep, speak, flash_console
from automation.core.logging import log_verbose, log_normal, LOG_VERBOSITY
from automation.core.hotkeys import (
    check_hotkeys_polled,
    toggle_pause,
    trigger_extra_wait,
    is_paused,
    set_paused,
    extra_wait_until,
    set_extra_wait_until,
)
from automation.core.session import SessionStats

__all__ = [
    # Audio
    "beep",
    "speak", 
    "flash_console",
    # Logging
    "log_verbose",
    "log_normal",
    "LOG_VERBOSITY",
    # Hotkeys
    "check_hotkeys_polled",
    "toggle_pause",
    "trigger_extra_wait",
    "is_paused",
    "set_paused",
    "extra_wait_until",
    "set_extra_wait_until",
    # Session
    "SessionStats",
]
