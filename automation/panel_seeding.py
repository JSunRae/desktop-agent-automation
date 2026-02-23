"""Prompt seeding workflow for finished panels."""

from __future__ import annotations

import time
import keyboard
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING
import typing

from automation.config import (
    ENABLE_KEEP_EDITS_CONFIRMATION,
    ENABLE_NEW_CHAT_RETRY,
    ENABLE_ROBUST_PANEL_PROCESSING,
    MODEL_PICKER_LABELS,
)
from automation.metrics import get_metrics_tracker
from automation.core.hotkeys import check_hotkeys_polled, is_paused
from automation.panel_state import (
    PanelState,
    PanelStatus,
    extract_repo_name_from_title,
)
from automation.panel_task_dispatcher import (
    TaskFeedEntry,
    build_task_id,
    compute_prompt_identifier as dispatcher_compute_prompt_identifier,
    detect_model_label as dispatcher_detect_model_label,
    get_repo_prompt_cache_key,
    load_prompt_blocks as dispatcher_load_prompt_blocks,
    load_prompt_blocks_for_repo as dispatcher_load_prompt_blocks_for_repo,
    preview_prompt_text as dispatcher_preview_prompt_text,
)
from automation.panel_tracker_core import PanelTracker
from automation.panel_ui import iter_controls, send_text_to_chat
from automation import prompt_resolver

if TYPE_CHECKING:
    import uiautomation as auto

NEW_CHAT_KEYWORD = "new chat"
CHAT_INPUT_KEYWORDS: tuple[str, ...] = (
    "new chat editor",
    "chat input",
    "message copilot",
    "type your instructions",
    "start typing",
    "prompt copilot",
    "send a message",
)


def _resolve_repo_prompt_path(repo_name: Optional[str]) -> Path:
    return prompt_resolver.resolve_prompt_path_for_repo(repo_name)


def resolve_prompt_path_for_window(window_title: str) -> Path:
    return prompt_resolver.resolve_prompt_path_for_window_title(window_title)


def _get_repo_prompt_cache_key(repo_name: Optional[str]) -> str:
    return get_repo_prompt_cache_key(repo_name)


def _compute_prompt_identifier(prompt_text: str) -> str:
    return dispatcher_compute_prompt_identifier(prompt_text)


def _preview_prompt_text(prompt_text: str) -> str:
    return dispatcher_preview_prompt_text(prompt_text)


def _load_prompt_blocks(prompt_path: Optional[Path] = None) -> List[str]:
    return dispatcher_load_prompt_blocks(prompt_path)


def _load_prompt_blocks_for_repo(repo_name: Optional[str]) -> List[str]:
    return dispatcher_load_prompt_blocks_for_repo(repo_name)


def _detect_model_label(prompt_text: str) -> str:
    full_label = dispatcher_detect_model_label(prompt_text)
    if not full_label:
        return ""
    for _key, picker_label in MODEL_PICKER_LABELS.items():
        if picker_label and picker_label.lower() == full_label.lower():
            return picker_label
    return full_label


def _resolve_panel_identity(panel: Optional[PanelState] = None, panel_title: str = "", panel_id: str = "") -> tuple[str, str]:
    title = panel.window_title if panel else (panel_title or "Unknown")
    identifier = panel.panel_id if panel else panel_id
    return title, identifier or ""


def _record_keep_flow_event(*, step: str, status: str, detail: Optional[str] = None, panel: Optional[PanelState] = None, panel_title: str = "", panel_id: str = "") -> None:
    title, identifier = _resolve_panel_identity(panel, panel_title, panel_id)
    try:
        metrics = get_metrics_tracker()
        metrics.record_keep_new_chat_event(title, identifier, step, status, detail)
    except Exception:
        return


def _ensure_panel_window_focus(vs_win: "auto.Control", *, panel: Optional[PanelState] = None, panel_title: str = "", panel_id: str = "", step: str) -> bool:
    title, identifier = _resolve_panel_identity(panel, panel_title, panel_id)
    try:
        from automation.ui.button_clicker import ensure_window_focus as _ensure_focus

        success = _ensure_focus(vs_win, description=title)
        detail = None if success else "foreground_mismatch"
    except Exception:
        success = False
        detail = "ensure_window_focus_unavailable"

    _record_keep_flow_event(
        step=f"{step}_focus",
        status="success" if success else "failure",
        detail=detail,
        panel=panel,
        panel_title=panel_title,
        panel_id=panel_id,
    )

    if not success:
        print(f"[PanelTracker] Unable to focus '{title[:50]}' before {step} step")

    return success


def _try_click_keep_edits(vs_win: "auto.Control", panel: PanelState) -> tuple[bool, bool]:
    focus_ready = _ensure_panel_window_focus(vs_win, panel=panel, step="keep")
    if not focus_ready:
        return False, False

    try:
        from automation.ui import click_all_action_buttons
    except Exception as exc:
        _record_keep_flow_event(step="keep_edits", status="failure", detail=str(exc), panel=panel)
        return False, True

    try:
        clicked, _ = click_all_action_buttons(vs_win)
        was_clicked = clicked.get("keep_edits", 0) > 0

        _record_keep_flow_event(
            step="keep_edits",
            status="success" if was_clicked else "skipped",
            detail=None if was_clicked else "keep_button_not_found",
            panel=panel,
        )

        if was_clicked and ENABLE_KEEP_EDITS_CONFIRMATION:
            # Delegate deep OK-dialog handling to panel_followups helper to
            # benefit from its wait-and-recheck logic.
            try:
                from automation.panel_followups import handle_keep_edits_confirmation_dialog

                ok_clicked = handle_keep_edits_confirmation_dialog(vs_win)
            except Exception as exc:  # noqa: BLE001
                _record_keep_flow_event(step="ok_button", status="failure", detail=str(exc), panel=panel)
                return was_clicked, True

            if ok_clicked:
                _record_keep_flow_event(step="ok_button", status="success", panel=panel)
            else:
                _record_keep_flow_event(step="ok_button", status="skipped", detail="not_found", panel=panel)
        elif ENABLE_KEEP_EDITS_CONFIRMATION:
            _record_keep_flow_event(step="ok_button", status="skipped", detail="keep_not_clicked", panel=panel)

        return was_clicked, True
    except Exception as exc:
        _record_keep_flow_event(step="keep_edits", status="failure", detail=str(exc), panel=panel)
        return False, True


def _find_new_chat_button(vs_win: "auto.Control") -> Optional["auto.Control"]:
    try:
        import uiautomation as auto
    except Exception:
        return None

    for ctrl in iter_controls(vs_win, max_depth=40):
        try:
            if isinstance(ctrl, auto.ButtonControl):
                name = (ctrl.Name or "").strip().lower()
                if name and NEW_CHAT_KEYWORD in name:
                    return ctrl
        except Exception:
            continue
    return None


def _find_chat_input_control(vs_win: "auto.Control") -> Optional["auto.Control"]:
    try:
        import uiautomation as auto
    except Exception:
        return None

    best: Optional["auto.Control"] = None
    best_score = -1.0
    for ctrl in iter_controls(vs_win, max_depth=55):
        try:
            if not isinstance(ctrl, (auto.EditControl, auto.DocumentControl, auto.TextControl)):
                continue
            name = (ctrl.Name or "").strip().lower()
            score = 0.0
            if any(keyword in name for keyword in CHAT_INPUT_KEYWORDS):
                score += 5.0
            try:
                rect = ctrl.BoundingRectangle
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width > 0 and height > 0:
                    score += height / 200.0
                    score += rect.top / 10000.0
            except Exception:
                pass
            if score > best_score:
                best_score = score
                best = ctrl
        except Exception:
            continue
    return best


def _focus_control(control: Optional["auto.Control"]) -> bool:
    if control is None:
        return False

    from automation.ui.window_utils import get_cursor_pos, set_cursor_pos

    original_pos = get_cursor_pos()
    try:
        try:
            control.SetFocus()
            return True
        except Exception:
            try:
                rect = control.BoundingRectangle
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 0 or height <= 0:
                    return False
                center_x = rect.left + width // 2
                center_y = rect.top + height // 2
                set_cursor_pos(center_x, center_y)
                time.sleep(0.05)
                control.Click(simulateMove=False)
                return True
            except Exception:
                return False
    finally:
        try:
            set_cursor_pos(original_pos[0], original_pos[1])
        except Exception:
            pass
    return False


def _find_model_picker_button(vs_win: "auto.Control") -> Optional["auto.Control"]:
    try:
        import uiautomation as auto
    except Exception:
        return None

    for ctrl in iter_controls(vs_win, max_depth=35):
        try:
            if isinstance(ctrl, auto.MenuItemControl):
                name = (ctrl.Name or "").lower()
                if "pick model" in name:
                    return ctrl
        except Exception:
            continue
    return None


def _select_model(vs_win: "auto.Control", label: str) -> bool:
    if not label:
        return False
    btn = _find_model_picker_button(vs_win)
    if btn is None:
        return False

    try:
        btn.Click(simulateMove=False)
        time.sleep(0.2)
    except Exception:
        return False

    try:
        import uiautomation as auto

        item = auto.MenuItemControl(searchDepth=6, Name=label)
        if item.Exists(0.5):
            item.Click(simulateMove=False)
            time.sleep(0.1)
            return True
    except Exception:
        return False

    return False


def _open_new_chat(vs_win: "auto.Control") -> tuple[bool, str]:
    max_retries = 3 if ENABLE_NEW_CHAT_RETRY else 1
    for attempt in range(max_retries):
        btn = _find_new_chat_button(vs_win)
        if btn is None:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            return False, "button_not_found"
        try:
            btn.Click(simulateMove=False)
            time.sleep(0.4)
            keyboard.send("ctrl+n")
            time.sleep(0.2)

            # Wait for chat input to appear and be focusable
            deadline = time.time() + 5.0
            while time.time() < deadline:
                ctrl = _find_chat_input_control(vs_win)
                if ctrl and _focus_control(ctrl):
                    return True, "clicked_and_focused"
                time.sleep(0.5)

            return False, "input_not_found_after_click"
        except Exception as exc:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            return False, f"click_error:{exc}"
    return False, "unknown_failure"


def _seed_prompt_in_window(vs_win: "auto.Control", prompt_text: str, panel_title: str = "", prompt_index: int = -1, panel_id: str = "") -> bool:
    panel_title = panel_title or getattr(vs_win, "Name", "Unknown") or "Unknown"
    identifier = panel_id or ""

    if not _ensure_panel_window_focus(vs_win, panel_title=panel_title, panel_id=identifier, step="new_chat"):
        return False

    opened, detail = _open_new_chat(vs_win)
    _record_keep_flow_event(step="new_chat_open", status="success" if opened else "failure", detail=detail, panel_title=panel_title, panel_id=identifier)
    if not opened:
        print("[PanelTracker] Could not open New Chat for finished panel")
        return False

    model_label = _detect_model_label(prompt_text)
    if model_label:
        success = _select_model(vs_win, model_label)
        metrics = get_metrics_tracker()
        metrics.record_model_selection(panel_title, model_label, success)

    result = send_text_to_chat(vs_win, prompt_text)
    _record_keep_flow_event(step="prompt_send", status="success" if result else "failure", panel_title=panel_title, panel_id=identifier, detail=None if result else "send_text_failed")

    if panel_title and prompt_index >= 0:
        metrics = get_metrics_tracker()
        metrics.record_prompt_seeding(
            panel_title=panel_title,
            prompt_index=prompt_index,
            prompt_text=prompt_text,
            model_requested=model_label,
            success=result,
            error_message=None if result else "Failed to send text to chat",
        )

        if identifier:
            prompt_id = _compute_prompt_identifier(prompt_text)
            repo = extract_repo_name_from_title(panel_title)
            metrics.record_assignment(
                prompt_id=prompt_id,
                panel_id=identifier,
                panel_title=panel_title,
                repo=repo,
                outcome="success" if result else "failure",
            )

    return result


def _update_retry_backoff(tracker: PanelTracker, panel: PanelState, reason: str) -> int:
    """Update panel retry metadata using exponential backoff.

    Backoff schedule (by attempt number):
      1 -> 60s, 2 -> 300s, 3+ -> 900s.
    Returns the backoff in seconds that was applied.
    """

    try:
        current = panel.seed_retry_count or 0
    except AttributeError:
        # Older PanelState without retry fields – no backoff applied.
        return 0

    attempt_number = current + 1
    if attempt_number == 1:
        delay_seconds = 60
    elif attempt_number == 2:
        delay_seconds = 300
    else:
        delay_seconds = 900

    panel.seed_retry_count = attempt_number
    panel.needs_retry = True
    panel.seed_last_failure_reason = reason
    panel.seed_next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)

    try:
        tracker._save_state()
    except Exception:
        pass

    return delay_seconds


def process_finished_panels_with_prompts(tracker: PanelTracker, vs_windows: List["auto.Control"]) -> int:
    """Drive finished panels: keep edits, open new chat, seed prompt batch.

    Implements retry tracking with exponential backoff and emits
    telemetry for each seeding attempt.
    """

    # NOTE: Many tests monkeypatch helpers on `automation.panel_tracker`.
    # Use late-binding through that module to preserve compatibility.
    from automation import panel_tracker as pt

    if not pt.ENABLE_FINISHED_PANEL_FOLLOWUPS:
        return 0

    tracker.update_panel_status()
    try:
        finished_panels = tracker.get_finished_panels_for_seeding()  # type: ignore[attr-defined]
    except AttributeError:
        # Older tracker without retry-aware helper – fall back to legacy API.
        finished_panels = tracker.get_finished_panels()

    if not finished_panels:
        return 0

    dispatcher = pt.get_task_panel_dispatcher()

    try:
        if not tracker.repo_prompt_indices and tracker.next_prompt_index == 0:
            feed_cache = getattr(dispatcher, "_feed_cache", None)
            if feed_cache:
                reset_cache = getattr(dispatcher, "reset_cache", None)
                if callable(reset_cache):
                    reset_cache()
    except Exception:
        pass

    def dispatcher_has_feed_entries(repo_name: Optional[str]) -> bool:
        """Return True if the dispatcher feed still has tasks for a repo."""
        if not repo_name:
            return False

        try:
            get_cache = getattr(dispatcher, "_get_feed_cache", None)
            if callable(get_cache):
                cache = get_cache(repo_name)
                entries = getattr(cache, "entries", None)
                if entries:
                    return True
        except Exception:
            pass

        try:
            get_entries = getattr(dispatcher, "_get_feed_entries", None)
            if callable(get_entries):
                return bool(get_entries(repo_name))
        except Exception:
            pass

        return False

    dispatcher.sync_active_assignments(typing.cast(typing.Any, tracker))
    dispatcher.track_idle_panels([
        tracker.build_panel_key(panel)
        for panel in finished_panels
        if not panel.seeded_prompt
    ])

    processed = 0

    window_map: Dict[str, "auto.Control"] = {}
    for vs_win in vs_windows:
        try:
            title = vs_win.Name or ""
            if title:
                window_map[title] = vs_win
        except Exception:
            continue

    for panel in finished_panels:
        check_hotkeys_polled()
        if is_paused():
            print("[PanelTracker] Seeding interrupted by pause")
            break

        if panel.seeded_prompt:
            continue

        assignment = None
        panel_key = tracker.build_panel_key(panel)

        try:
            vs_win_maybe = window_map.get(panel.window_title)
            if vs_win_maybe is None:
                continue
            vs_win = typing.cast("auto.Control", vs_win_maybe)

            panel_output_text = panel.last_output_sample or ""
            classification = pt.classify_panel_output(panel_output_text)
            if classification != "IDLE_SAFE":
                print(
                    f"[PanelTracker] Skipping prompt seeding for {panel.window_title[:50]} "
                    f"- classified as {classification}"
                )
                continue

            repo_name = panel.repo_name or pt.extract_repo_name_from_title(panel.window_title)
            panel.repo_name = repo_name

            assignment = dispatcher.reserve_task_for_panel(
                tracker=typing.cast(typing.Any, tracker),
                panel=typing.cast(typing.Any, panel),
                panel_key=panel_key,
                repo_name=repo_name,
            )
            if assignment is None:
                # Dispatcher could not assign a task. If the repo has no feed entries at all
                # (missing/empty feed), fall back to the legacy round-robin prompt loader.
                # If the feed exists but is exhausted (entries present but all assigned), skip.
                if dispatcher_has_feed_entries(repo_name):
                    continue

                legacy_prompts = pt._load_prompt_blocks_for_repo(repo_name)
                if not legacy_prompts:
                    continue

                legacy_index = tracker.get_prompt_index_for_repo(repo_name, len(legacy_prompts))
                prompt_to_send = legacy_prompts[legacy_index]
                tracker.advance_prompt_index(repo_name, steps=1)

                prompt_id = pt._compute_prompt_identifier(prompt_to_send)
                task_id = build_task_id(repo_name, prompt_id or str(legacy_index))

                assignment = TaskFeedEntry(
                    repo_key=get_repo_prompt_cache_key(repo_name),
                    repo_name=repo_name,
                    prompt_index=legacy_index,
                    prompt_text=prompt_to_send,
                    prompt_preview=pt._preview_prompt_text(prompt_to_send),
                    prompt_id=prompt_id or str(legacy_index),
                    task_id=task_id,
                    model_label=pt._detect_model_label(prompt_to_send) or "",
                    source_path=pt._resolve_prompt_path_for_repo(repo_name),
                    batch_id=None,
                )

                # Reserve the synthetic assignment so multiple panels don't reuse it in-run.
                try:
                    getattr(dispatcher, "_active_assignments")[task_id] = panel_key
                except Exception:
                    pass

            prompt_to_send = assignment.prompt_text
            panel.assigned_prompt_index = assignment.prompt_index
            panel.assigned_prompt_id = assignment.prompt_id or str(assignment.prompt_index)
            panel.assigned_prompt_text = assignment.prompt_preview
            panel.assignment_time = datetime.now()
            panel.assigned_task_id = assignment.task_id
            panel.assigned_task_name = assignment.prompt_preview.splitlines()[0] if assignment.prompt_preview else None
            panel.assignment_batch_id = assignment.batch_id
            panel.assignment_source = str(assignment.source_path)
            panel.assigned_model_label = getattr(assignment, "model_label", None) or None
            panel.assignment_attempts += 1

            attempt_number = getattr(panel, "seed_retry_count", 0) + 1

            if pt.FINISHED_PANEL_DRY_RUN:
                print(
                    "[PanelTracker][DRY-RUN] Would keep edits, open new chat, and send prompt "
                    f"{(panel.assigned_prompt_index or 0) + 1}"
                    f" to: {panel.window_title[:50]}"
                )
                panel.seeded_prompt = True
                tracker._record_transcript_snapshot(panel, kind=pt.TRANSCRIPT_KIND_SEED_PROMPT, text=prompt_to_send)
                tracker._save_state()
                try:
                    metrics = get_metrics_tracker()
                    metrics.record_seeding_attempt(
                        panel_title=panel.window_title,
                        panel_id=panel.panel_id,
                        attempt_number=attempt_number,
                        success=True,
                        failure_reason="dry_run",
                        backoff_seconds=None,
                    )
                except Exception:
                    pass
                processed += 1
                continue

            _keep_clicked, focus_ready = pt._try_click_keep_edits(vs_win, panel)
            if not focus_ready:
                print(
                    f"[PanelTracker] Skipping prompt seeding for {panel.window_title[:50]}"
                    " because the window focus could not be verified after Keep."
                )
                backoff_seconds = _update_retry_backoff(tracker, panel, "focus_not_verified_after_keep")
                try:
                    metrics = get_metrics_tracker()
                    metrics.record_seeding_attempt(
                        panel_title=panel.window_title,
                        panel_id=panel.panel_id,
                        attempt_number=attempt_number,
                        success=False,
                        failure_reason="focus_not_verified_after_keep",
                        backoff_seconds=backoff_seconds,
                    )
                except Exception:
                    pass
                dispatcher.release_task(assignment.task_id, panel_key)
                continue

            if pt._seed_prompt_in_window(
                vs_win,
                prompt_to_send,
                panel.window_title,
                panel.assigned_prompt_index or -1,
                panel.panel_id,
            ):
                panel.seeded_prompt = True
                panel.status = PanelStatus.RUNNING
                panel.last_allow_click = datetime.now()
                panel.needs_retry = False
                panel.seed_retry_count = 0
                panel.seed_last_failure_reason = None
                panel.seed_next_retry_at = None
                tracker._record_transcript_snapshot(panel, kind=pt.TRANSCRIPT_KIND_SEED_PROMPT, text=prompt_to_send)
                tracker._save_state()
                try:
                    metrics = get_metrics_tracker()
                    metrics.record_seeding_attempt(
                        panel_title=panel.window_title,
                        panel_id=panel.panel_id,
                        attempt_number=attempt_number,
                        success=True,
                        failure_reason=None,
                        backoff_seconds=None,
                    )
                except Exception:
                    pass
                processed += 1
            else:
                dispatcher.release_task(assignment.task_id, panel_key)
                backoff_seconds = _update_retry_backoff(tracker, panel, "seed_prompt_failed")
                print(f"[PanelTracker] Failed to seed prompt in {panel.window_title[:50]}")
                try:
                    metrics = get_metrics_tracker()
                    metrics.record_seeding_attempt(
                        panel_title=panel.window_title,
                        panel_id=panel.panel_id,
                        attempt_number=attempt_number,
                        success=False,
                        failure_reason="seed_prompt_failed",
                        backoff_seconds=backoff_seconds,
                    )
                except Exception:
                    pass

        except Exception as e:
            if assignment is not None:
                dispatcher.release_task(assignment.task_id, panel_key)
            if ENABLE_ROBUST_PANEL_PROCESSING:
                print(f"[PanelTracker] Error processing finished panel {panel.window_title[:30]}: {e}")
                try:
                    backoff_seconds = _update_retry_backoff(tracker, panel, f"exception:{type(e).__name__}")
                    metrics = get_metrics_tracker()
                    metrics.record_seeding_attempt(
                        panel_title=panel.window_title,
                        panel_id=panel.panel_id,
                        attempt_number=getattr(panel, "seed_retry_count", 1),
                        success=False,
                        failure_reason=f"exception:{type(e).__name__}",
                        backoff_seconds=backoff_seconds,
                    )
                except Exception:
                    pass
                continue
            raise

    return processed
