"""Follow-up workflows for finished / rate-limited panels."""

from __future__ import annotations

from datetime import datetime
from time import sleep
from typing import Dict, List, TYPE_CHECKING, cast

from automation.config import ENABLE_KEEP_EDITS_CONFIRMATION, ENABLE_SEND_TO_INACTIVE_PANELS
from automation.panel_classification import (
    check_output_for_next_steps,
    check_output_for_task_completed,
    is_prompt_generator_panel,
)
from automation.panel_state import IdleReason, PanelStatus
from automation.panel_tracker_core import PanelTracker
from automation.panel_ui import get_panel_output_text, send_text_to_chat

if TYPE_CHECKING:
    import uiautomation as auto


NEXT_STEPS_RESPONSE = (
    "Review your thought process and recommendations. "
    "You may continue working on the next steps as you best recommend."
)

COMPLETION_CHECK_PROMPT = (
    "If you have completed your task please respond with exactly 'task completed', "
    "if you have follow up actions you recommend, respond with 'next steps' and your proposal."
)

PLEASE_CONTINUE_PROMPT = "please continue"


def handle_keep_edits_confirmation_dialog(vs_win: "auto.Control", search_depth: int = 35) -> bool:
    """Look for and click an 'OK' confirmation dialog after Keep Edits.

    Uses a short wait-and-recheck pattern with a relatively deep
    search depth to cope with slow UI updates. Returns True if an
    OK button was found and clicked, False otherwise.
    """

    if not ENABLE_KEEP_EDITS_CONFIRMATION:
        return False

    try:
        import uiautomation as auto
        from automation.ui.button_clicker import click_button_with_verification
    except Exception:
        return False

    # First quick check
    try:
        ok_btn = auto.ButtonControl(searchFromControl=vs_win, searchDepth=search_depth, Name="OK")
        if ok_btn.Exists(0.5):
            return click_button_with_verification(ok_btn, "OK button")
    except Exception:
        pass

    # Allow dialog a bit of time to appear before a deeper pass.
    sleep(2.0)

    try:
        ok_btn = auto.ButtonControl(searchFromControl=vs_win, searchDepth=search_depth, Name="OK")
        if ok_btn.Exists(0.5):
            return click_button_with_verification(ok_btn, "OK button (delayed)")
    except Exception:
        pass

    return False


def process_finished_panels(tracker: PanelTracker, vs_windows: List["auto.Control"]) -> int:
    """Legacy follow-up flow (completion check / next steps)."""
    if not ENABLE_SEND_TO_INACTIVE_PANELS:
        return 0

    tracker.update_panel_status()
    panels_needing_attention = tracker.get_finished_panels_needing_attention()
    if not panels_needing_attention:
        return 0

    processed = 0

    window_map: Dict[str, "auto.Control"] = {}
    for vs_win in vs_windows:
        try:
            title = vs_win.Name or ""
            if title:
                window_map[title] = vs_win
        except Exception:
            continue

    for panel in panels_needing_attention:
        vs_win_maybe = window_map.get(panel.window_title)
        if vs_win_maybe is None:
            continue
        vs_win = cast("auto.Control", vs_win_maybe)

        try:
            output_text = get_panel_output_text(vs_win)

            if is_prompt_generator_panel(output_text):
                print(f"[PanelTracker] Skipping prompt generator panel: {panel.window_title[:50]}")
                panel.status = PanelStatus.COMPLETED
                tracker._save_state()
                continue

            has_next_steps = check_output_for_next_steps(output_text)

            if has_next_steps and not panel.sent_next_steps_response:
                print(f"\n[PanelTracker] Panel has 'next steps' - sending response: {panel.window_title[:50]}")
                if send_text_to_chat(vs_win, NEXT_STEPS_RESPONSE):
                    tracker.mark_next_steps_response_sent(panel.window_title, panel.panel_id)
                    processed += 1
                    panel.status = PanelStatus.RUNNING
                    panel.last_allow_click = datetime.now()

            elif not panel.sent_completion_check:
                print(f"\n[PanelTracker] Sending completion check to: {panel.window_title[:50]}")
                if send_text_to_chat(vs_win, COMPLETION_CHECK_PROMPT):
                    tracker.mark_completion_check_sent(panel.window_title, panel.panel_id)
                    processed += 1
                    panel.status = PanelStatus.RUNNING
                    panel.last_allow_click = datetime.now()

        except Exception as e:
            print(f"[PanelTracker] Error processing panel {panel.window_title[:30]}: {e}")

    return processed


def process_rate_limited_panels(tracker: PanelTracker, vs_windows: List["auto.Control"]) -> int:
    if not ENABLE_SEND_TO_INACTIVE_PANELS:
        return 0

    processed = 0

    window_map: Dict[str, "auto.Control"] = {}
    for vs_win in vs_windows:
        try:
            title = vs_win.Name or ""
            if title:
                window_map[title] = vs_win
        except Exception:
            continue

    for _key, panel in tracker.panels.items():
        if panel.idle_reason != IdleReason.RATE_LIMITED_NO_BUTTON:
            continue
        if panel.sent_please_continue:
            continue

        vs_win_maybe = window_map.get(panel.window_title)
        if vs_win_maybe is None:
            continue
        vs_win = cast("auto.Control", vs_win_maybe)

        try:
            output_text = get_panel_output_text(vs_win)
            if is_prompt_generator_panel(output_text):
                print(f"[PanelTracker] Skipping prompt generator (rate limited): {panel.window_title[:50]}")
                panel.status = PanelStatus.COMPLETED
                tracker._save_state()
                continue

            print(f"\n[PanelTracker] Rate limited (no button) - sending 'please continue': {panel.window_title[:50]}")
            if send_text_to_chat(vs_win, PLEASE_CONTINUE_PROMPT):
                panel.sent_please_continue = True
                panel.last_allow_click = datetime.now()
                processed += 1
                tracker._save_state()
        except Exception as e:
            print(f"[PanelTracker] Error sending 'please continue': {e}")

    return processed


def check_for_task_completed(tracker: PanelTracker, vs_win: "auto.Control") -> bool:
    try:
        window_title = vs_win.Name or "Unknown"
        output_text = get_panel_output_text(vs_win)

        if check_output_for_task_completed(output_text):
            tracker.mark_completed(window_title, completion_text=output_text)
            return True
    except Exception as e:
        print(f"[PanelTracker] Error checking for task completed: {e}")

    return False
