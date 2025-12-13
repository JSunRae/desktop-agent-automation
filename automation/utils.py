"""
Shared utility functions for Desktop Agent Automation.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

def ensure_log_file(log_path: Path) -> None:
    """Create log file if it doesn't exist."""
    import sys
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.touch()
    except (OSError, IOError) as e:
        print(f"Warning: Failed to create log file directory or file {log_path}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected error ensuring log file {log_path}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

def log_message(message: str, log_path: Optional[Path] = None, print_to_console: bool = True) -> None:
    """
    Write a timestamped message to the log file and/or console.
    
    Args:
        message: The message to log
        log_path: Optional path to the log file. If None, only prints to console.
        print_to_console: Whether to print the message to stdout.
    """
    import traceback
    import sys
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    
    if print_to_console:
        print(log_line)
        
    if log_path:
        try:
            ensure_log_file(log_path)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except (OSError, IOError) as e:
            # Log to stderr if file logging fails
            print(f"Warning: Failed to write to log file {log_path}: {e}", file=sys.stderr)
        except Exception as e:
            # Catch any other unexpected errors
            print(f"Unexpected error writing to log file {log_path}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
