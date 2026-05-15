"""
Main orchestration loop for desktop agent automation.

This module contains the primary run loop that:
- Polls for hotkeys and manages pause states
- Scans virtual desktops for VS Code windows
- Clicks Allow/Keep Edits buttons
- Handles rate limiting and cooldowns
- Tracks panel states for follow-up actions
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from enum import IntEnum
from typing import Dict, List, Optional, Union

import uiautomation as auto

from automation.config import (
    AUTO_PAUSE_ON_KEYBOARD_INPUT,
    AUTO_PAUSE_ON_TYPING,
    COPILOT_USAGE_MONITOR_INTERVAL_SECONDS,
    DESKTOP_RECHECK_AFTER_FAILURES,
    DESKTOP_RESCAN_DELAY_SECONDS,
    ENABLE_COPILOT_USAGE_MONITOR,
    # Alerts
    ENABLE_NO_CLICK_ALERT,
    # Health checks
    ENABLE_PANEL_HEALTH_CHECK_SCHEDULING,
    ENABLE_PANEL_INSPECT_SCHEDULING,
    # Toast shortcut
    ENABLE_VSCODE_TOAST_SHORTCUT,
    # Rate limits
    MAX_ALLOWS_PER_HOUR,
    MAX_DESKTOP_RESCAN_PASSES,
    # Timing
    MIN_SCAN_INTERVAL_SECONDS,
    NO_CLICK_ALERT_MINUTES,
    PANEL_HEALTH_CHECK_INTERVAL_MINUTES,
    PANEL_INSPECT_INTERVAL_MINUTES,
    PANEL_INSPECT_SCHEDULE_SUITE,
    PANEL_INSPECT_TARGET_REPO,
    PANEL_INSPECT_TIMEOUT_SECONDS,
    # Keys
    PAUSE_HOTKEY,
    # Desktop
    PRIORITY_DESKTOP,
    SPEAK_PAUSE_EVENTS,
    # Features
    USE_CACHED_HANDLES,
)
from automation.copilot_usage_monitor import CopilotUsageMonitor
from automation.core.audio import speak
from automation.core.hotkeys import (
    check_hotkeys_polled,
    check_mouse_interrupts,
    extra_wait_until,
    is_auto_paused,
    is_keyboard_activity_detected,
    is_paused,
    request_manual_pause,
    set_auto_paused,
)
from automation.core.logging import log_normal, log_verbose
from automation.core.session import (
    increment_allow_clicks,
    increment_keep_edits_clicks,
)
from automation.cost_tracker import get_cost_tracker
from automation.desktop import (
    get_desktops_to_check,
    needs_desktop_switch,
    switch_to_desktop,
)
from automation.desktop.reliability import (
    get_cycles_since_check,
    get_failure_count,
    increment_desktop_cycles,
    record_desktop_result,
    should_skip_desktop,
)
from automation.desktop.window_cache import (
    get_cached_vscode_windows,
    get_desktop_for_handle,
    refresh_window_cache,
    should_refresh_cache,
)
from automation.panel_tracker import get_tracker, process_finished_panels_with_prompts
from automation.rate_limit import (
    format_rate_status,
    get_cooldown_remaining,
    is_in_cooldown,
    load_allow_events,
)
from automation.rate_monitor import RateMonitor  # NEW
from automation.task_discovery_daemon import (
    start_task_discovery_daemon,
    stop_task_discovery_daemon,
)
from automation.ui import (
    click_all_action_buttons,
    find_all_vscode_windows,
    get_foreground_window,
    get_try_again_cooldown_remaining,
    is_try_again_cooldown_active,
    partition_windows_by_priority,
    sort_windows_by_priority,
    try_consume_vscode_toast,
)

# ============================================================================
# QUICK PANEL STATE DETECTION
# ============================================================================

QUICK_PANEL_SEARCH_DEPTH = 60

_ACTIVE_COPILOT_USAGE_MONITOR: Optional[CopilotUsageMonitor] = None


def _maybe_poll_copilot_usage(
    *,
    now: datetime,
    last_checked_at: datetime,
    monitor: Optional[CopilotUsageMonitor],
) -> datetime:
    if not ENABLE_COPILOT_USAGE_MONITOR or monitor is None:
        return last_checked_at
    if (now - last_checked_at).total_seconds() < COPILOT_USAGE_MONITOR_INTERVAL_SECONDS:
        return last_checked_at

    try:
        snapshot = monitor.poll_once()
        if snapshot.alert:
            print(
                f"[{now}] {snapshot.alert} "
                f"({snapshot.percentage or 0.0:.1f}% used vs {snapshot.calendar_progress:.1f}% calendar progress)"
            )
    except Exception as exc:
        log_verbose(f"Copilot usage monitor poll failed: {exc}")
    return now


def _start_copilot_usage_monitor() -> Optional[CopilotUsageMonitor]:
    global _ACTIVE_COPILOT_USAGE_MONITOR

    if not ENABLE_COPILOT_USAGE_MONITOR:
        return None
    if _ACTIVE_COPILOT_USAGE_MONITOR is not None:
        return _ACTIVE_COPILOT_USAGE_MONITOR

    monitor = CopilotUsageMonitor(
        cost_tracker=get_cost_tracker(),
        interval_seconds=COPILOT_USAGE_MONITOR_INTERVAL_SECONDS,
    )
    monitor.start()
    _ACTIVE_COPILOT_USAGE_MONITOR = monitor
    print(
        f"[USAGE_MONITOR] Copilot usage monitor started "
        f"(interval={monitor.interval_seconds:g}s)"
    )
    return monitor


def _stop_copilot_usage_monitor() -> None:
    global _ACTIVE_COPILOT_USAGE_MONITOR

    if _ACTIVE_COPILOT_USAGE_MONITOR is None:
        return

    try:
        _ACTIVE_COPILOT_USAGE_MONITOR.stop()
    finally:
        _ACTIVE_COPILOT_USAGE_MONITOR = None


class QuickPanelState(IntEnum):
    """Quick-detect panel states for prioritization."""
    UNKNOWN = 0
    RUNNING = 1   # Has Cancel button - agent is working
    WAITING = 2   # Has Allow button - waiting for approval
    FINISHED = 3  # No Cancel, no Allow - agent completed


def detect_panel_state_quick(vs_win: auto.Control) -> tuple:
    """
    Quickly detect panel state by looking for key indicators.
    
    Returns:
        (QuickPanelState, has_cancel: bool, has_allow: bool)
    """
    has_cancel = False
    has_allow = False
    
    try:
        # Look for Cancel button (indicates running)
        cancel_btn = vs_win.ButtonControl(searchDepth=QUICK_PANEL_SEARCH_DEPTH, Name="Cancel")
        if cancel_btn.Exists(0.05):
            has_cancel = True
        
        # Look for Allow button (indicates waiting)
        # Note: Button names include keyboard shortcuts like "Allow (Ctrl+Enter)"
        # so we need to search by substring or try multiple names
        allow_btn = vs_win.ButtonControl(searchDepth=QUICK_PANEL_SEARCH_DEPTH, Name="Allow (Ctrl+Enter)")
        if allow_btn.Exists(0.05):
            has_allow = True
        else:
            # Try the short name as fallback
            allow_btn = vs_win.ButtonControl(searchDepth=QUICK_PANEL_SEARCH_DEPTH, Name="Allow")
            if allow_btn.Exists(0.05):
                has_allow = True
            else:
                # Final fallback: substring search for any Allow button
                try:
                    generic_allow = vs_win.Control(
                        searchDepth=QUICK_PANEL_SEARCH_DEPTH,
                        ControlType=auto.ControlType.ButtonControl,
                        Lambda=lambda c: bool(getattr(c, "Name", None)) and "allow" in c.Name.lower(),
                    )
                    if generic_allow.Exists(0.05):
                        has_allow = True
                except Exception as e:
                    log_verbose(f"Error in generic allow button search: {e}")
    except Exception as e:
        log_verbose(f"Error detecting panel state for window {getattr(vs_win, 'Name', 'Unknown')}: {e}")
    
    if has_cancel:
        return QuickPanelState.RUNNING, has_cancel, has_allow
    elif has_allow:
        return QuickPanelState.WAITING, has_cancel, has_allow
    else:
        return QuickPanelState.FINISHED, has_cancel, has_allow


def get_panel_states_summary(windows: List[auto.Control]) -> dict:
    """Get a count of each panel state across all windows."""
    counts = {
        QuickPanelState.RUNNING: 0,
        QuickPanelState.WAITING: 0,
        QuickPanelState.FINISHED: 0,
        QuickPanelState.UNKNOWN: 0,
    }
    for win in windows:
        state, _, _ = detect_panel_state_quick(win)
        counts[state] += 1
    return counts


# ============================================================================
# NO-WINDOWS LOOP DETECTION
# ============================================================================

_no_windows_loop_counter: int = 0
NO_WINDOWS_LOOP_WARN_THRESHOLD = 10


def handle_no_windows_loop(now: datetime) -> bool:
    """
    Track consecutive no-windows cycles and warn if stuck.
    
    Returns:
        True if we should force a desktop resync
    """
    global _no_windows_loop_counter
    
    _no_windows_loop_counter += 1
    
    if _no_windows_loop_counter >= NO_WINDOWS_LOOP_WARN_THRESHOLD:
        if _no_windows_loop_counter == NO_WINDOWS_LOOP_WARN_THRESHOLD:
            speak("No windows found in loop. Check desktop positions.")
            print(f"\n⚠️  WARNING: {_no_windows_loop_counter} consecutive 'no windows' cycles!")
            print("   This usually means:")
            print("   1. Desktop position got confused (try manual switch)")
            print("   2. All VS Code windows are minimized")
            print("   3. DESKTOPS_TO_CHECK doesn't match actual layout")
        
        # Force resync every 10 iterations
        if _no_windows_loop_counter % 10 == 0:
            print("  → Forcing desktop resync...")
            return True
    
    return False


def reset_no_windows_loop_counter() -> None:
    """Reset the no-windows loop counter after finding windows."""
    global _no_windows_loop_counter
    _no_windows_loop_counter = 0


# ============================================================================
# AUTO-PAUSE ON TYPING
# ============================================================================

_last_input_activity: datetime = datetime.now()
AUTO_PAUSE_IDLE_THRESHOLD_MS = 500  # Resume after 500ms idle


def detect_recent_user_input(now: datetime) -> tuple:
    """
    Check if user is actively typing.
    
    Returns:
        (is_active: bool, idle_seconds: Optional[float])
    """
    try:
        import ctypes
        
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        
        current_tick = ctypes.windll.kernel32.GetTickCount()
        idle_ms = current_tick - lii.dwTime
        
        if idle_ms < 0:
            idle_ms += 0xFFFFFFFF  # Handle tick count rollover
        
        is_active = idle_ms < AUTO_PAUSE_IDLE_THRESHOLD_MS
        idle_seconds = idle_ms / 1000.0
        
        return is_active, idle_seconds
    except Exception as e:
        log_verbose(f"Failed to detect user input: {e}")
        return False, None


# ============================================================================
# SLEEP WITH HOTKEY/MOUSE POLLING
# ============================================================================

def sleep_with_hotkey_checks(total_seconds: float, poll_seconds: float = 0.05) -> None:
    """Sleep in short slices while still honoring hotkeys and mouse interrupts."""
    deadline = time.time() + max(0.0, total_seconds)

    while True:
        check_hotkeys_polled()

        now_dt = datetime.now()
        if is_paused() or extra_wait_until() > now_dt:
            break

        remaining = deadline - time.time()
        if remaining <= 0:
            break

        time.sleep(min(poll_seconds, remaining))


# ============================================================================
# ORCHESTRATION LOOP
# ============================================================================

def run_main_loop(desktops_list: Optional[List[Union[int, str]]] = None) -> None:
    """
    Main automation loop.
    
    Args:
        desktops_list: List of desktop names/numbers to check. If None, uses config.
    """
    # Initialize
    if desktops_list is None:
        desktops_list = get_desktops_to_check()
    
    load_allow_events()
    tracker = get_tracker()
    
    # Initialize RateMonitor
    rate_monitor = RateMonitor()

    no_click_alerted = False
    last_click_activity = datetime.now()
    no_click_force_refresh_loops = 0  # consecutive no-click loops for cache refresh
    last_cost_report = datetime.now()
    cost_report_interval_minutes = 15
    last_panel_health_check = datetime.now()
    last_panel_inspect_check = datetime.now()
    _start_copilot_usage_monitor()
    start_task_discovery_daemon()
    
    print(f"\n[{datetime.now()}] Starting automation loop")
    print(f"  Desktops to check: {desktops_list}")
    print(f"  Rate limit: {MAX_ALLOWS_PER_HOUR} allows/hour")
    print(f"  Pause hotkey: {PAUSE_HOTKEY}")
    print()

    status_line_width = 140
    status_line_last_text: Optional[str] = None

    def _status_line(text: str) -> None:
        nonlocal status_line_last_text

        # Append rate status to the text
        rate_status = format_rate_status()
        full_text = f"{text} | {rate_status}"

        # Skip writes if the content didn't actually change.
        if full_text == status_line_last_text:
            return

        status_line_last_text = full_text
        line = full_text[:status_line_width].ljust(status_line_width)
        # Use carriage returns so countdown/status messages overwrite themselves instead of spamming new lines.
        sys.stdout.write("\r" + line)
        sys.stdout.flush()

    def _clear_status_line() -> None:
        nonlocal status_line_last_text

        if status_line_last_text is None:
            return

        status_line_last_text = None
        sys.stdout.write("\r" + " " * status_line_width)
        sys.stdout.flush()

    def _wait_remaining() -> float:
        """Seconds left in extra-wait window (0 if none)."""
        now_dt = datetime.now()
        return max(0.0, (extra_wait_until() - now_dt).total_seconds())

    def _click_actions_on_foreground_vscode() -> dict:
        """Best-effort attempt to click action buttons on the focused VS Code window."""
        clicked: dict = {"allow": 0, "keep_edits": 0, "rate_limited": False}
        try:
            hwnd = get_foreground_window()
            if not hwnd:
                return clicked

            ctrl = auto.ControlFromHandle(hwnd)
            if not ctrl or not ctrl.Exists(0.2):
                return clicked

            try:
                title = ctrl.Name or ""
            except Exception:
                title = ""

            if "visual studio code" not in title.lower():
                return clicked

            result, _ = click_all_action_buttons(ctrl)
            clicked.update(result)
            return clicked
        except Exception as exc:
            log_verbose(f"Toast shortcut click failed: {exc}")
            return clicked

    def _run_scheduled_panel_inspect() -> None:
        suite = (PANEL_INSPECT_SCHEDULE_SUITE or "scan").strip().lower()
        if suite not in {"scan", "overlap", "response", "refresh", "all"}:
            suite = "scan"

        command = [sys.executable, "scripts/panel_inspect.py", "--suite", suite]
        target_repo = (PANEL_INSPECT_TARGET_REPO or "").strip()
        if target_repo:
            command.extend(["--target-repo", target_repo])

        target_label = target_repo or "<all repos>"
        print(f"[{datetime.now()}] Running scheduled panel inspect (suite={suite}, target={target_label})")
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(5, PANEL_INSPECT_TIMEOUT_SECONDS),
            )
            if completed.returncode != 0:
                stderr_preview = (completed.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
                print(
                    f"[{datetime.now()}] Scheduled panel inspect failed "
                    f"(exit={completed.returncode}): {stderr_preview[0]}"
                )
            else:
                print(f"[{datetime.now()}] Scheduled panel inspect completed")
        except subprocess.TimeoutExpired:
            print(
                f"[{datetime.now()}] Scheduled panel inspect timed out after "
                f"{max(5, PANEL_INSPECT_TIMEOUT_SECONDS)}s"
            )
        except Exception as exc:
            print(f"[{datetime.now()}] Scheduled panel inspect error: {exc}")
    
    try:
        while True:
            now = datetime.now()

            # Monitor rate conditions
            try:
                rate_monitor.check(is_paused())
            except Exception as e:
                log_verbose(f"Rate monitor error: {e}")

            # Safety: if the user is pressing keys, pause immediately so we don't fight for control.
            if AUTO_PAUSE_ON_KEYBOARD_INPUT:
                try:
                    if is_keyboard_activity_detected():
                        request_manual_pause("Keyboard activity detected")
                        time.sleep(0.1)
                        continue
                except Exception as exc:
                    log_verbose(f"Keyboard activity detection failed: {exc}")

            # Detect significant physical mouse movement or drift to give the user time to intervene.
            # This is now handled centrally in hotkeys.py to ensure it works during long operations.
            drift_status = check_mouse_interrupts()
            if drift_status:
                _status_line(drift_status)
                time.sleep(0.1)
                continue
            elif is_paused():
                # If we're paused but not in a drift pause, clear any drift status line.
                _clear_status_line()

            # Check for auto-pause on typing
            if AUTO_PAUSE_ON_TYPING:
                user_active, idle_seconds = detect_recent_user_input(now)

                if user_active:
                    if not is_auto_paused():
                        set_auto_paused(True)
                        print(f"\n[{now}] ⌨️  Typing detected - auto-paused")
                        if SPEAK_PAUSE_EVENTS:
                            speak("Auto paused")
                    time.sleep(0.1)
                    continue
                elif is_auto_paused():
                    set_auto_paused(False)
                    idle_note = f" (~{idle_seconds:.1f}s idle)" if idle_seconds else ""
                    print(f"[{now}] ✓ Typing idle - resuming automation{idle_note}\n")
                    if SPEAK_PAUSE_EVENTS:
                        speak("Resumed")

            # Check if manually paused
            if is_paused():
                rate_status = format_rate_status()
                print(f"[{now}] Manually paused - press {PAUSE_HOTKEY} to resume... ({rate_status})")
                for _ in range(20):
                    check_hotkeys_polled()
                    if not is_paused():
                        break
                    time.sleep(0.1)
                continue

            # Check if in extra wait period
            wait_until = extra_wait_until()
            if now < wait_until:
                remaining = (wait_until - now).total_seconds()
                _status_line(f"Extra wait: {remaining:5.0f}s left | {PAUSE_HOTKEY} to toggle pause")
                for _ in range(20):
                    check_hotkeys_polled()
                    time.sleep(0.1)
                if datetime.now() >= wait_until:
                    _clear_status_line()
                continue

            # Check cooldown
            if is_in_cooldown(now):
                remaining = get_cooldown_remaining(now)
                print(f"[{now}] In cooldown ({remaining:.0f}s left)...")
                for _ in range(50):
                    check_hotkeys_polled()
                    time.sleep(0.1)
                continue

            # Check Try Again cooldown (triggered when multiple Try Again buttons detected)
            if is_try_again_cooldown_active():
                remaining = get_try_again_cooldown_remaining()
                print(f"[{now}] 🔴 Rate limit cooldown ({remaining:.0f}s left) - detected via Try Again buttons...")
                for _ in range(50):
                    check_hotkeys_polled()
                    time.sleep(0.1)
                continue

            # ================================================================
            # VS CODE TOAST SHORTCUT (fast path)
            # ================================================================
            toast_allow_clicked = 0
            toast_keep_clicked = 0
            rate_limited_detected = False

            if ENABLE_VSCODE_TOAST_SHORTCUT:
                try:
                    handled, toast_text = try_consume_vscode_toast()
                    if handled:
                        # Give Windows a brief moment to foreground VS Code after the toast click.
                        time.sleep(0.25)
                        clicked = _click_actions_on_foreground_vscode()
                        toast_allow_clicked += clicked.get("allow", 0)
                        toast_keep_clicked += clicked.get("keep_edits", 0)
                        rate_limited_detected = bool(clicked.get("rate_limited"))

                        if toast_allow_clicked or toast_keep_clicked:
                            summary_parts = []
                            if toast_allow_clicked:
                                summary_parts.append(f"{toast_allow_clicked} Allow")
                            if toast_keep_clicked:
                                summary_parts.append(f"{toast_keep_clicked} Keep Edits")
                            summary = ", ".join(summary_parts)
                            toast_note = f" | {toast_text}" if toast_text else ""
                            print(f"[{now}] Toast shortcut clicked {summary}{toast_note}")
                            increment_allow_clicks(toast_allow_clicked)
                            increment_keep_edits_clicks(toast_keep_clicked)
                except Exception as exc:
                    log_verbose(f"Toast shortcut handling failed: {exc}")

                if rate_limited_detected:
                    # Respect cooldown logic on next iteration
                    continue

            # ================================================================
            # WINDOW SCANNING
            # ================================================================
            scan_attempted = True
            total_allow_clicked = toast_allow_clicked
            total_keep_edits_clicked = toast_keep_clicked
            total_vscode_windows = 0
            pause_requested_mid_cycle = False
            wait_requested_mid_cycle = False
            checked_idle_panels = False

            if USE_CACHED_HANDLES and desktops_list != [0]:
                # CACHED MODE
                if should_refresh_cache(now):
                    refresh_window_cache(desktops_list, force=True)

                vscode_windows = get_cached_vscode_windows()

                if vscode_windows:
                    total_vscode_windows = len(vscode_windows)
                    if tracker is not None:
                        tracker.refresh_priority_scores(now)

                    # Partition windows into live and idle groups
                    # Live panels (RUNNING, WAITING_ALLOW, RATE_LIMITED) are processed first
                    # Idle panels (IDLE, FINISHED, COMPLETED, STALE) only when no live work
                    live_windows, idle_windows = partition_windows_by_priority(vscode_windows)
                    if tracker is not None:
                        live_windows = tracker.sort_windows_by_priority(live_windows)
                        idle_windows = tracker.sort_windows_by_priority(idle_windows)

                    # ============================================================
                    # PHASE 1: Process LIVE panels (highest priority)
                    # ============================================================
                    if live_windows:
                        rescan_pass = 0
                        max_rescan = MAX_DESKTOP_RESCAN_PASSES or None

                        while True:
                            check_hotkeys_polled()
                            if is_paused():
                                pause_requested_mid_cycle = True
                                break
                            if _wait_remaining() > 0:
                                wait_requested_mid_cycle = True
                                break

                            rescan_pass += 1
                            allow_this_pass = 0
                            keep_this_pass = 0

                            # Group windows by desktop to minimize switching
                            windows_by_desktop: Dict[Union[int, str], List[int]] = {}
                            desktop_scores: Dict[Union[int, str], float] = {}
                            for win in live_windows:
                                try:
                                    hwnd = win.NativeWindowHandle
                                    desktop = get_desktop_for_handle(hwnd)
                                    if desktop is None or not hwnd:
                                        continue
                                    windows_by_desktop.setdefault(desktop, []).append(hwnd)
                                    if tracker is not None:
                                        try:
                                            title = win.Name or ""
                                        except Exception:
                                            title = ""
                                        score = tracker.compute_window_priority_score(title)
                                        desktop_scores[desktop] = max(desktop_scores.get(desktop, 0.0), score)
                                except Exception:
                                    continue

                            # Process each desktop
                            ordered_desktops = sorted(
                                windows_by_desktop.items(),
                                key=lambda item: desktop_scores.get(item[0], 0.0),
                                reverse=True,
                            )

                            for desktop, hwnds in ordered_desktops:
                                check_hotkeys_polled()
                                if is_paused():
                                    pause_requested_mid_cycle = True
                                    break
                                if _wait_remaining() > 0:
                                    wait_requested_mid_cycle = True
                                    break

                                # Switch desktop if needed to ensure UI tree is accessible
                                if needs_desktop_switch(desktop):
                                    switch_to_desktop(desktop)
                                    # Small wait for UI to settle while still watching hotkeys/mouse
                                    sleep_with_hotkey_checks(0.2)

                                refreshed_windows: List[auto.Control] = []
                                for hwnd in hwnds:
                                    try:
                                        ctrl = auto.ControlFromHandle(hwnd)
                                        if ctrl and ctrl.Exists(0.2):
                                            refreshed_windows.append(ctrl)
                                    except Exception:
                                        continue

                                if tracker is not None:
                                    refreshed_windows = tracker.sort_windows_by_priority(refreshed_windows)

                                for vs_win in refreshed_windows:
                                    check_hotkeys_polled()
                                    if is_paused():
                                        pause_requested_mid_cycle = True
                                        break
                                    if _wait_remaining() > 0:
                                        wait_requested_mid_cycle = True
                                        break

                                    try:
                                        # Verify window is still valid
                                        _ = vs_win.Name
                                    except Exception:
                                        continue

                                    # Call button finder directly - it handles all button types
                                    clicked, _ = click_all_action_buttons(vs_win)
                                    allow_this_pass += clicked['allow']
                                    keep_this_pass += clicked['keep_edits']

                                    # Check if we hit rate limit
                                    if clicked.get('rate_limited'):
                                        rate_limited_detected = True
                                        break

                                if rate_limited_detected:
                                    break
                                if wait_requested_mid_cycle:
                                    break

                            total_allow_clicked += allow_this_pass
                            total_keep_edits_clicked += keep_this_pass
                            increment_allow_clicks(allow_this_pass)
                            increment_keep_edits_clicks(keep_this_pass)

                            # Stop if rate limited
                            if rate_limited_detected:
                                break
                            if wait_requested_mid_cycle:
                                break

                            if allow_this_pass + keep_this_pass == 0:
                                break

                            print(f"  Clicked {allow_this_pass + keep_this_pass} button(s) on LIVE panels (pass {rescan_pass})")

                            if max_rescan and rescan_pass >= max_rescan:
                                break

                            sleep_with_hotkey_checks(DESKTOP_RESCAN_DELAY_SECONDS)

                            # Re-partition in case panel states changed
                            vscode_windows = get_cached_vscode_windows()
                            if not vscode_windows:
                                break
                            live_windows, idle_windows = partition_windows_by_priority(vscode_windows)
                            if not live_windows:
                                break

                    # ============================================================
                    # PHASE 2: Check IDLE panels only if no live work found
                    # ============================================================
                    if not pause_requested_mid_cycle and not wait_requested_mid_cycle and not rate_limited_detected and idle_windows:
                        # Always sweep idle panels to catch Allow dialogs that weren't classified as live
                        checked_idle_panels = True
                        idle_allow = 0
                        idle_keep = 0

                        # Group windows by desktop
                        idle_windows_by_desktop: Dict[Union[int, str], List[int]] = {}
                        for win in idle_windows:
                            try:
                                hwnd = win.NativeWindowHandle
                                desktop = get_desktop_for_handle(hwnd)
                                if desktop is not None and hwnd:
                                    if desktop not in idle_windows_by_desktop:
                                        idle_windows_by_desktop[desktop] = []
                                    idle_windows_by_desktop[desktop].append(hwnd)
                            except Exception:
                                continue

                        # Process each desktop
                        for desktop, hwnds in idle_windows_by_desktop.items():
                            check_hotkeys_polled()
                            if is_paused():
                                pause_requested_mid_cycle = True
                                break
                            if _wait_remaining() > 0:
                                wait_requested_mid_cycle = True
                                break

                            if needs_desktop_switch(desktop):
                                switch_to_desktop(desktop)
                                sleep_with_hotkey_checks(0.2)

                            refreshed_idle_windows: List[auto.Control] = []
                            for hwnd in hwnds:
                                try:
                                    ctrl = auto.ControlFromHandle(hwnd)
                                    if ctrl and ctrl.Exists(0.2):
                                        refreshed_idle_windows.append(ctrl)
                                except Exception:
                                    continue

                            for vs_win in refreshed_idle_windows:
                                check_hotkeys_polled()
                                if is_paused():
                                    pause_requested_mid_cycle = True
                                    break
                                if _wait_remaining() > 0:
                                    wait_requested_mid_cycle = True
                                    break

                                try:
                                    # Verify window is still valid
                                    _ = vs_win.Name
                                except Exception:
                                    continue

                                clicked, _ = click_all_action_buttons(vs_win)
                                idle_allow += clicked['allow']
                                idle_keep += clicked['keep_edits']

                                # Check if we hit rate limit
                                if clicked.get('rate_limited'):
                                    rate_limited_detected = True
                                    break
                                if wait_requested_mid_cycle:
                                    break

                            if rate_limited_detected:
                                break
                            if wait_requested_mid_cycle:
                                break

                        if idle_allow + idle_keep > 0:
                            print(f"  Found {idle_allow + idle_keep} button(s) on previously idle panels")
                            total_allow_clicked += idle_allow
                            total_keep_edits_clicked += idle_keep
                            increment_allow_clicks(idle_allow)
                            increment_keep_edits_clicks(idle_keep)

                    # ============================================================
                    # PHASE 3: Hourly check - ensure all panels scanned within 1 hour
                    # ============================================================
                    if not pause_requested_mid_cycle and not wait_requested_mid_cycle and not rate_limited_detected:
                        try:
                            tracker = get_tracker()
                            panels_needing_check = tracker.get_panels_needing_hourly_check()

                            if panels_needing_check:
                                hourly_allow = 0
                                hourly_keep = 0

                                # Find the corresponding windows for these panels
                                all_windows = get_cached_vscode_windows()
                                for panel in panels_needing_check:
                                    check_hotkeys_polled()
                                    if is_paused():
                                        pause_requested_mid_cycle = True
                                        break
                                    if _wait_remaining() > 0:
                                        wait_requested_mid_cycle = True
                                        break

                                    # Find window matching this panel
                                    matching_window = None
                                    for win in all_windows:
                                        try:
                                            if win.Name == panel.window_title:
                                                matching_window = win
                                                break
                                        except Exception:
                                            continue

                                    if matching_window:
                                        # Get desktop and switch if needed
                                        try:
                                            hwnd = matching_window.NativeWindowHandle
                                            desktop = get_desktop_for_handle(hwnd)
                                            if desktop is not None and needs_desktop_switch(desktop):
                                                switch_to_desktop(desktop)
                                                sleep_with_hotkey_checks(0.2)

                                            # Refresh the control and check for buttons
                                            ctrl = auto.ControlFromHandle(hwnd)
                                            if ctrl and ctrl.Exists(0.2):
                                                clicked, _ = click_all_action_buttons(ctrl)
                                                hourly_allow += clicked['allow']
                                                hourly_keep += clicked['keep_edits']

                                                if clicked.get('rate_limited'):
                                                    rate_limited_detected = True
                                                    break
                                        except Exception:
                                            continue

                                if hourly_allow + hourly_keep > 0:
                                    print(f"  Found {hourly_allow + hourly_keep} button(s) on hourly check panels")
                                    total_allow_clicked += hourly_allow
                                    total_keep_edits_clicked += hourly_keep
                                    increment_allow_clicks(hourly_allow)
                                    increment_keep_edits_clicks(hourly_keep)
                        except Exception as e:
                            # Don't fail the whole loop if hourly check fails
                            print(f"  [WARNING] Hourly check failed: {e}")
                else:
                    print(f"[{now}] Cache empty - refreshing...")
                    refresh_window_cache(desktops_list, force=True)

            else:
                # LEGACY MODE - Switch desktops
                if desktops_list == [0]:
                    desktops_to_process: List[Union[int, str]] = [0]
                else:
                    desktops_to_process = []
                    other_desktops = [d for d in desktops_list if d != PRIORITY_DESKTOP]
                    if PRIORITY_DESKTOP in desktops_list:
                        desktops_to_process.append(PRIORITY_DESKTOP)
                    desktops_to_process.extend(other_desktops)

                current_desktop: Optional[Union[int, str]] = None

                for desktop_num in desktops_to_process:
                    check_hotkeys_polled()
                    if is_paused():
                        pause_requested_mid_cycle = True
                        break
                    if _wait_remaining() > 0:
                        wait_requested_mid_cycle = True
                        break

                    desktop_label = "current" if desktop_num == 0 else str(desktop_num)
                    is_priority = desktop_num == PRIORITY_DESKTOP

                    # Check if should skip due to failures
                    if isinstance(desktop_num, int) and desktop_num > 0:
                        if should_skip_desktop(desktop_num):
                            failures = get_failure_count(desktop_num)
                            cycles = get_cycles_since_check(desktop_num)
                            remaining = DESKTOP_RECHECK_AFTER_FAILURES - cycles
                            log_normal(f"  → Skipping {desktop_label} (failed {failures}x, recheck in {remaining})")
                            continue

                    # Switch desktop if needed
                    if needs_desktop_switch(desktop_num) and current_desktop != desktop_num:
                        priority_note = " [PRIORITY]" if is_priority else ""
                        log_normal(f"  → Switching to {desktop_label}{priority_note}...")
                        switch_to_desktop(desktop_num)
                        current_desktop = desktop_num
                        sleep_with_hotkey_checks(0.5)

                    # Find windows with retry
                    vscode_windows = []
                    for attempt in range(1, 4):
                        vscode_windows = find_all_vscode_windows()
                        if vscode_windows:
                            break
                        if needs_desktop_switch(desktop_num) and attempt < 3:
                            wait = 1.0 + (attempt * 0.5)
                            log_verbose(f"  ⚠ Retry {attempt}/3: No windows on {desktop_label}, waiting {wait}s...")
                            sleep_with_hotkey_checks(wait)

                    if not vscode_windows:
                        if needs_desktop_switch(desktop_num):
                            log_normal(f"  ⚠ No VS Code windows on {desktop_label}")
                            if isinstance(desktop_num, int):
                                record_desktop_result(desktop_num, found_windows=False)
                        continue

                    # Found windows
                    if isinstance(desktop_num, int):
                        record_desktop_result(desktop_num, found_windows=True)
                    total_vscode_windows += len(vscode_windows)
                    vscode_windows = sort_windows_by_priority(vscode_windows)

                    # Process windows
                    rescan_pass = 0
                    max_rescan = MAX_DESKTOP_RESCAN_PASSES or None

                    while True:
                        check_hotkeys_polled()
                        if is_paused():
                            pause_requested_mid_cycle = True
                            break
                        if _wait_remaining() > 0:
                            wait_requested_mid_cycle = True
                            break

                        rescan_pass += 1
                        allow_this_pass = 0
                        keep_this_pass = 0

                        for vs_win in vscode_windows:
                            check_hotkeys_polled()
                            if is_paused():
                                pause_requested_mid_cycle = True
                                break
                            if _wait_remaining() > 0:
                                wait_requested_mid_cycle = True
                                break

                            try:
                                # Verify window is still valid
                                _ = vs_win.Name
                            except Exception:
                                continue

                            # Call button finder directly - it handles all button types
                            clicked, _ = click_all_action_buttons(vs_win)
                            allow_this_pass += clicked['allow']
                            keep_this_pass += clicked['keep_edits']

                            # Check if we hit rate limit
                            if clicked.get('rate_limited'):
                                rate_limited_detected = True
                                break
                            if wait_requested_mid_cycle:
                                break

                        total_allow_clicked += allow_this_pass
                        total_keep_edits_clicked += keep_this_pass
                        increment_allow_clicks(allow_this_pass)
                        increment_keep_edits_clicks(keep_this_pass)

                        # Stop if rate limited
                        if rate_limited_detected:
                            break

                        if allow_this_pass + keep_this_pass == 0:
                            break

                        print(f"  Clicked {allow_this_pass + keep_this_pass} on {desktop_label} (pass {rescan_pass})")

                        if max_rescan and rescan_pass >= max_rescan:
                            break

                        sleep_with_hotkey_checks(DESKTOP_RESCAN_DELAY_SECONDS)
                        vscode_windows = find_all_vscode_windows()
                        if not vscode_windows:
                            break
                        vscode_windows = sort_windows_by_priority(vscode_windows)

                    if pause_requested_mid_cycle or wait_requested_mid_cycle or rate_limited_detected:
                        break

            if pause_requested_mid_cycle or wait_requested_mid_cycle:
                if wait_requested_mid_cycle and not pause_requested_mid_cycle:
                    remaining = _wait_remaining()
                    print(f"\n[{datetime.now()}] Extra wait active ({remaining:0.0f}s left)...")
                else:
                    print(f"\n[{datetime.now()}] Manual pause detected. Holding...")
                sleep_with_hotkey_checks(1)
                continue

            # If rate limited, the cooldown was already triggered - just continue to next iteration
            if rate_limited_detected:
                continue

            # Check if we found any windows
            if total_vscode_windows == 0:
                force_resync = handle_no_windows_loop(now)
                if force_resync:
                    continue
                print(f"[{now}] No VS Code windows found, sleeping {MIN_SCAN_INTERVAL_SECONDS}s...")
                if ENABLE_NO_CLICK_ALERT:
                    last_click_activity = now
                    no_click_alerted = False
                sleep_with_hotkey_checks(MIN_SCAN_INTERVAL_SECONDS)
                continue

            reset_no_windows_loop_counter()

            # Report results
            total_clicked = total_allow_clicked + total_keep_edits_clicked
            rate_status = format_rate_status(now)

            if total_clicked > 0:
                summary = []
                if total_allow_clicked > 0:
                    summary.append(f"{total_allow_clicked} Allow")
                if total_keep_edits_clicked > 0:
                    summary.append(f"{total_keep_edits_clicked} Keep Edits")
                idle_note = " (from idle scan)" if checked_idle_panels else ""
                print(f"[{now}] Clicked {', '.join(summary)}{idle_note}. [{rate_status}]")
                no_click_force_refresh_loops = 0
            else:
                idle_note = " (checked idle panels too)" if checked_idle_panels else ""
                print(f"[{now}] No action buttons found{idle_note}. [{rate_status}]")
                if USE_CACHED_HANDLES and desktops_list != [0]:
                    no_click_force_refresh_loops += 1
                    if no_click_force_refresh_loops >= 3:
                        print(f"[{datetime.now()}] 🔄 No clicks in {no_click_force_refresh_loops} loops — forcing cache refresh")
                        refresh_window_cache(desktops_list, force=True)
                        no_click_force_refresh_loops = 0

            # Increment desktop cycle counters
            increment_desktop_cycles()

            # Handle finished panels: keep edits, open new chat, and seed prompts (flag-gated)
            try:
                followup_windows = find_all_vscode_windows()
                process_finished_panels_with_prompts(followup_windows)
            except Exception:
                pass

            # Track no-click alert timer (only during active scan attempts)
            if ENABLE_NO_CLICK_ALERT and scan_attempted and total_vscode_windows > 0:
                if total_clicked > 0:
                    last_click_activity = now
                    no_click_alerted = False
                else:
                    inactivity = (now - last_click_activity).total_seconds()
                    if (not no_click_alerted) and inactivity >= NO_CLICK_ALERT_MINUTES * 60:
                        print(f"[{now}] ⚠️  No action clicks in {NO_CLICK_ALERT_MINUTES} minutes of active scanning")
                        try:
                            speak(f"No action clicks in {NO_CLICK_ALERT_MINUTES} minutes")
                        except Exception:
                            pass
                        no_click_alerted = True

            # Print cost totals periodically
            if (now - last_cost_report).total_seconds() >= cost_report_interval_minutes * 60:
                try:
                    cost_tracker = get_cost_tracker()
                    totals = cost_tracker.get_session_totals()
                    if totals.get("total_cost", 0) > 0:
                        print(f"\n💰 Session spend: ${totals['total_cost']:.4f} "
                              f"({totals['input_tokens']:,} in + {totals['output_tokens']:,} out tokens, "
                              f"{totals['vision_images']} images)")
                    last_cost_report = now
                except Exception:
                    pass

            # Periodic panel_state.json health checks (flag-gated)
            if ENABLE_PANEL_HEALTH_CHECK_SCHEDULING:
                try:
                    if (now - last_panel_health_check).total_seconds() >= PANEL_HEALTH_CHECK_INTERVAL_MINUTES * 60:
                        from scripts import health_check_panels as _health

                        _health.run_health_check(auto_repair=True, quiet=True)
                        last_panel_health_check = now
                except Exception:
                    pass

            # Periodic panel inspection scan (flag-gated, dry-run by default)
            if ENABLE_PANEL_INSPECT_SCHEDULING:
                try:
                    if (now - last_panel_inspect_check).total_seconds() >= PANEL_INSPECT_INTERVAL_MINUTES * 60:
                        _run_scheduled_panel_inspect()
                        last_panel_inspect_check = now
                except Exception:
                    pass

            # Just wait the minimum interval before next scan
            # Rate limiting is now detected via Try Again buttons, not per-hour limits
            if tracker is not None:
                tracker.save_state()
            sleep_with_hotkey_checks(MIN_SCAN_INTERVAL_SECONDS)
    finally:
        stop_task_discovery_daemon()
        _stop_copilot_usage_monitor()
