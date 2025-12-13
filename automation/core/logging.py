"""
Logging utilities with verbosity control.

Provides log functions that respect the LOG_VERBOSITY setting:
- "quiet": Only important events (errors, rate limits, etc.)
- "normal": Standard output (default)
- "verbose": All details including debug info
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Log verbosity control
# "normal" = standard output (default), "quiet" = only important events, "verbose" = all details
LOG_VERBOSITY = os.environ.get("LOG_VERBOSITY", "normal").lower()

# Optional file logging
LOG_FILE_PATH: Optional[Path] = None


def set_log_file(path: Path | str | None) -> None:
    """Set the log file path for persistent logging."""
    global LOG_FILE_PATH
    LOG_FILE_PATH = Path(path) if path else None


def log_verbose(msg: str) -> None:
    """
    Print message only if LOG_VERBOSITY is 'verbose'.
    
    Use for detailed debugging information that's usually too noisy.
    
    Args:
        msg: Message to print
    """
    if LOG_VERBOSITY == "verbose":
        print(msg)
        _write_to_file(msg, "VERBOSE")


def log_normal(msg: str) -> None:
    """
    Print message if LOG_VERBOSITY is 'normal' or 'verbose' (not 'quiet').
    
    Use for standard operational messages.
    
    Args:
        msg: Message to print
    """
    if LOG_VERBOSITY != "quiet":
        print(msg)
        _write_to_file(msg, "INFO")


def log_quiet(msg: str) -> None:
    """
    Print message regardless of LOG_VERBOSITY.
    
    Use for critical events that should always be shown:
    - Rate limit detection
    - Errors
    - Session start/stop
    
    Args:
        msg: Message to print
    """
    print(msg)
    _write_to_file(msg, "IMPORTANT")


def log_error(msg: str) -> None:
    """
    Print error message regardless of verbosity.
    
    Args:
        msg: Error message to print
    """
    print(f"ERROR: {msg}")
    _write_to_file(msg, "ERROR")


def log_warning(msg: str) -> None:
    """
    Print warning message if not in quiet mode.
    
    Args:
        msg: Warning message to print
    """
    if LOG_VERBOSITY != "quiet":
        print(f"⚠ {msg}")
        _write_to_file(msg, "WARNING")


def _write_to_file(msg: str, level: str) -> None:
    """Write message to log file if configured."""
    import sys
    import traceback
    
    if LOG_FILE_PATH is None:
        return
    
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} [{level}] {msg}\n")
    except (OSError, IOError) as e:
        print(f"Warning: Failed to write to log file {LOG_FILE_PATH}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected error writing to log file {LOG_FILE_PATH}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


def get_verbosity() -> str:
    """Get current verbosity level."""
    return LOG_VERBOSITY


def is_verbose() -> bool:
    """Check if verbose logging is enabled."""
    return LOG_VERBOSITY == "verbose"


def is_quiet() -> bool:
    """Check if quiet mode is enabled."""
    return LOG_VERBOSITY == "quiet"
