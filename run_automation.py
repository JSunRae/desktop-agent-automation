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
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

# Initialize configuration first
from automation.config import (
    DESKTOPS_TO_CHECK,
    MAX_ALLOWS_PER_HOUR,
    TASK_DISCOVERY_INTERVAL_SECONDS,
    TASK_DISCOVERY_LOW_TASK_THRESHOLD,
    TASK_DISCOVERY_AUTOSTART,
)
from automation.core.hotkeys import print_hotkey_info
from automation.core.session import get_session
from automation.rate_limit.tracker import load_allow_events, save_allow_events
from automation.orchestrator import run_main_loop
from automation.panel_tracker import get_tracker


def main() -> None:
    parser = argparse.ArgumentParser(description="Desktop Agent Automation")
    parser.add_argument(
        "--wait-minutes",
        type=int,
        default=0,
        help="Minutes to wait before starting automation",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Enable autonomous mode with background task discovery",
    )
    parser.add_argument(
        "--task-discovery-interval",
        type=int,
        default=None,
        help="Override task discovery interval in seconds (autonomous mode)",
    )
    parser.add_argument(
        "--task-discovery-low-threshold",
        type=int,
        default=None,
        help="Override low-task threshold before audit (autonomous mode)",
    )
    parser.add_argument(
        "--disable-task-discovery",
        action="store_true",
        help="Disable background task discovery even if autostart is enabled",
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

    start_task_discovery = (args.autonomous or TASK_DISCOVERY_AUTOSTART) and not args.disable_task_discovery

    if start_task_discovery:
        from automation.task_discovery_daemon import start_task_discovery_daemon
        from automation.cross_repo_todo_ingestion import get_cross_repo_todo_service

        print("Background task discovery enabled. Starting TaskDiscoveryDaemon...")
        daemon_kwargs = {}
        daemon_kwargs["interval_seconds"] = (
            args.task_discovery_interval
            if args.task_discovery_interval is not None
            else TASK_DISCOVERY_INTERVAL_SECONDS
        )
        daemon_kwargs["low_task_threshold"] = (
            args.task_discovery_low_threshold
            if args.task_discovery_low_threshold is not None
            else TASK_DISCOVERY_LOW_TASK_THRESHOLD
        )
        print(f"Task discovery settings: {daemon_kwargs}")
        start_task_discovery_daemon(**daemon_kwargs)

        # Show summary of discovered tasks
        todo_service = get_cross_repo_todo_service()
        snapshot = todo_service.get_snapshot(force_refresh=True)
        total_tasks = sum(len(repo.items) for repo in snapshot.repos)
        print(f"Repo audit complete. Discovered {total_tasks} Open Tasks across {len(snapshot.repos)} repositories.")
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
        get_tracker().save_state()

        if start_task_discovery:
            try:
                from automation.task_discovery_daemon import stop_task_discovery_daemon
                stop_task_discovery_daemon()
            except Exception:
                pass


if __name__ == "__main__":
    main()
