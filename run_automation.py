#!/usr/bin/env python3
"""
Desktop Agent Automation - Main Entry Point

This is a thin entry point that imports from the modular automation package
and runs the main orchestration loop.

The automation system:
- Scans VS Code windows across virtual desktops
- Clicks Allow, Keep Edits, and Try Again buttons
- Manages rate limiting to avoid hitting API limits
- Supports hotkey-based pause/resume

Usage:
    python run_automation.py

Configuration:
    Edit automation/config.py or set environment variables in .env

For the original monolithic script (deprecated), see auto_allow_copilot.py
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

# Initialize configuration first
from automation.config import (
    DESKTOPS_TO_CHECK,
    MAX_ALLOWS_PER_HOUR,
)
from automation.core.hotkeys import print_hotkey_info
from automation.core.session import get_session
from automation.rate_limit.tracker import load_allow_events, save_allow_events
from automation.orchestrator import run_main_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Desktop Agent Automation")
    parser.add_argument(
        "--wait-minutes",
        type=int,
        default=0,
        help="Minutes to wait before starting automation",
    )
    args = parser.parse_args()

    if args.wait_minutes > 0:
        print(f"Waiting {args.wait_minutes} minutes before starting...")
        time.sleep(args.wait_minutes * 60)
        print("Wait complete. Starting automation...")

    """Main entry point for the automation system."""
    print("=" * 60)
    print("Desktop Agent Automation")
    print("=" * 60)
    print(f"Started at: {datetime.now()}")
    print(f"Desktops to check: {DESKTOPS_TO_CHECK}")
    print(f"Rate limit: {MAX_ALLOWS_PER_HOUR} allows/hour")
    print()
    
    # Show hotkey info
    print("Hotkeys:")
    print_hotkey_info()
    print()
    
    # Load persisted allow events
    print("Loading persisted state...")
    load_allow_events()
    print()
    
    # Run the main loop
    try:
        run_main_loop()
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] KeyboardInterrupt - shutting down...")
    except Exception as e:
        import traceback
        import sys
        error_msg = f"Unexpected error in automation: {e}"
        print(f"[{datetime.now()}] ERROR: {error_msg}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    finally:
        # Print session summary
        session = get_session()
        session.print_summary()
        
        # Save state
        save_allow_events()


if __name__ == "__main__":
    main()
