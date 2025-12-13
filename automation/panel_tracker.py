"""Compatibility facade for panel tracking.

This module preserves the public API surface of the original monolithic
`automation.panel_tracker` while delegating implementations to smaller focused
modules (panel_state/panel_ui/panel_detection/panel_*).

Tests and runtime code frequently monkeypatch attributes on this module, so
several helper names remain defined here and are used via late binding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, cast

# ---------------------------------------------------------------------------
# Optional OpenAI dependency (tests monkeypatch `openai_module`).
# ---------------------------------------------------------------------------

openai_module: Any
try:
    import openai as _openai_module
except ImportError:
    _openai_module = cast(Any, None)
openai_module = _openai_module

# ---------------------------------------------------------------------------
# Configuration + env
# ---------------------------------------------------------------------------

import os

from dotenv import load_dotenv

load_dotenv()

from automation.config import (  # noqa: E402
    ENABLE_CLIPBOARD_TEXT_READING,
    ENABLE_FINISHED_PANEL_FOLLOWUPS,
    ENABLE_KEEP_EDITS_CONFIRMATION,
    ENABLE_NEW_CHAT_RETRY,
    ENABLE_ROBUST_PANEL_PROCESSING,
    ENABLE_SEND_TO_INACTIVE_PANELS,
    FINISHED_PANEL_DRY_RUN,
    FINISHED_PANEL_PROMPT_PATH,
    FINISHED_PANEL_REVIEW_BACKOFF_SECONDS,
    FINISHED_PANEL_REVIEW_MAX_RETRIES,
    FINISHED_PANEL_REVIEW_MODEL,
    FINISHED_PANEL_REVIEW_TEMPERATURE,
    FINISHED_PANEL_REVIEW_TRANSCRIPT_CHARS,
    MODEL_PICKER_LABELS,
    REPO_PROMPT_MAP,
    VSCODE_TITLE_SUFFIX,
)

from automation.cost_tracker import get_cost_tracker  # noqa: E402
from automation.metrics import get_metrics_tracker  # noqa: E402
from automation import prompt_resolver  # noqa: E402
from automation.panel_task_dispatcher import (  # noqa: E402
    ASSIGNED_PROMPT_ID_LEN,
    ASSIGNED_PROMPT_PREVIEW_CHARS,
    DEFAULT_REPO_PROMPT_KEY,
    compute_prompt_identifier as dispatcher_compute_prompt_identifier,
    detect_model_label as dispatcher_detect_model_label,
    get_repo_prompt_cache_key,
    get_task_panel_dispatcher,
    load_prompt_blocks as dispatcher_load_prompt_blocks,
    load_prompt_blocks_for_repo as dispatcher_load_prompt_blocks_for_repo,
    preview_prompt_text as dispatcher_preview_prompt_text,
)
from automation.response_parser import ResponseCategory, classify_response  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover
    import uiautomation as auto

# ---------------------------------------------------------------------------
# Re-exported state + core tracking
# ---------------------------------------------------------------------------

from automation.panel_state import (  # noqa: E402
    IdleReason,
    PanelState,
    PanelStatus,
    TranscriptSnapshot,
    TRANSCRIPT_FILTER_PLACEHOLDER,
    TRANSCRIPT_HASH_LEN,
    TRANSCRIPT_KIND_COMPLETION,
    TRANSCRIPT_KIND_REVIEW,
    TRANSCRIPT_KIND_SEED_PROMPT,
    TRANSCRIPT_MAX_SNAPSHOTS,
    TRANSCRIPT_PREVIEW_CHARS,
    extract_repo_name_from_title,
)

from automation.panel_tracker_core import (  # noqa: E402
    DEFAULT_PANEL_STATE_PATH,
    OUTPUT_SAMPLE_CHARS,
    PANEL_FINISHED_THRESHOLD_MINUTES,
    PANEL_IDLE_THRESHOLD_MINUTES,
    PANEL_STALE_THRESHOLD_MINUTES,
    PanelTracker,
)

# ---------------------------------------------------------------------------
# Re-exported UI + detection helpers
# ---------------------------------------------------------------------------

from automation.panel_detection import (  # noqa: E402
    detect_idle_reason,
    detect_panel_running_state,
    detect_panel_state_detailed,
    get_comprehensive_panel_state,
)

from automation.panel_ui import (  # noqa: E402
    _check_editor_has_text_via_clipboard,
    _get_clipboard_text,
    _set_clipboard_text,
    find_chat_editor_control,
    find_chat_input_box,
    find_send_button,
    get_chat_input_text,
    get_panel_output_text,
    iter_controls,
    send_text_to_chat,
)

# Share the same user-text guard set name as the legacy module.
from automation import panel_ui as _panel_ui  # noqa: E402

_panels_with_user_text = _panel_ui._panels_with_user_text

# ---------------------------------------------------------------------------
# Legacy prompt loading helpers (tests monkeypatch these names).
# ---------------------------------------------------------------------------


def _load_prompt_blocks(prompt_path: Optional[Path] = None) -> List[str]:
    return dispatcher_load_prompt_blocks(prompt_path)


def _load_prompt_blocks_for_repo(repo_name: Optional[str]) -> List[str]:
    return dispatcher_load_prompt_blocks_for_repo(repo_name)


def _compute_prompt_identifier(prompt_text: str) -> str:
    return dispatcher_compute_prompt_identifier(prompt_text)


def _preview_prompt_text(prompt_text: str) -> str:
    return dispatcher_preview_prompt_text(prompt_text)


def _detect_model_label(prompt_text: str) -> Optional[str]:
    return dispatcher_detect_model_label(prompt_text)


def _resolve_prompt_path_for_repo(repo_name: Optional[str]) -> Path:
    return prompt_resolver.resolve_prompt_path_for_repo(repo_name)


def resolve_prompt_path_for_window(window_title: str) -> Path:
    """Resolve which prompt feed path to use for a VS Code window title."""
    return prompt_resolver.resolve_prompt_path_for_window_title(window_title)


# ---------------------------------------------------------------------------
# Prompt seeding internals (tests monkeypatch these names).
# ---------------------------------------------------------------------------

from automation import panel_seeding as _panel_seeding  # noqa: E402

_try_click_keep_edits = _panel_seeding._try_click_keep_edits
_seed_prompt_in_window = _panel_seeding._seed_prompt_in_window

# ---------------------------------------------------------------------------
# Follow-up prompt messages (kept here for monkeypatch compatibility).
# ---------------------------------------------------------------------------

NEXT_STEPS_RESPONSE = (
    "Review your thought process and recommendations. "
    "You may continue working on the next steps as you best recommend."
)

COMPLETION_CHECK_PROMPT = (
    "If you have completed your task please respond with exactly 'task completed', "
    "if you have follow up actions you recommend, respond with 'next steps' and your proposal."
)

PLEASE_CONTINUE_PROMPT = "please continue"

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

PANEL_STATE_PATH = Path(__file__).parent / "panel_state.json"

_tracker: Optional[PanelTracker] = None


def get_tracker() -> PanelTracker:
    """Return the global PanelTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = PanelTracker(state_path=PANEL_STATE_PATH)
    return _tracker


def on_allow_click(window_title: str, panel_id: str = "") -> None:
    """Record that we clicked Allow/Keep on a panel."""
    get_tracker().record_allow_click(window_title, panel_id)


# ---------------------------------------------------------------------------
# Output classification (tests monkeypatch `openai_module` and `os.environ`).
# ---------------------------------------------------------------------------


def classify_panel_output(panel_text: str) -> str:
    """Classify panel output to decide if it's safe to seed new prompts.

    Returns "IDLE_SAFE" on API errors to maintain backward compatibility.
    """
    if not panel_text or not panel_text.strip():
        return "IDLE_SAFE"

    text_to_analyze = panel_text[-1000:].strip()

    if openai_module is None:
        print("[PanelTracker] OpenAI client not available, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[PanelTracker] OPENAI_API_KEY not set, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"

    try:
        client = openai_module.OpenAI(api_key=api_key)
        system_prompt = """You are an expert at analyzing Copilot chat panel output to determine if it's safe to send new prompts.

Classify the panel output into exactly one of these categories:

IDLE_SAFE: The panel appears to be idle and it's safe to send a new prompt.
ACTIVE_WORKING: The agent is currently working on a task.
COMPLETED: A task has been completed successfully.
AWAITING_USER: The agent is waiting for user input or clarification.

Respond with ONLY the classification category name, no explanation."""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Panel output:\n{text_to_analyze}"},
            ],
            max_tokens=10,
            temperature=0.1,
        )
        message_content = response.choices[0].message.content or ""
        classification = message_content.strip().upper()

        try:
            cost_tracker = get_cost_tracker()
            if hasattr(response, "usage"):
                cost_tracker.record_text_usage(
                    source="panel_tracker",
                    event="panel_classification",
                    model="gpt-4o-mini",
                    usage=response.usage,
                    details={"classification": classification},
                )
        except Exception:
            pass

        valid_categories = {"IDLE_SAFE", "ACTIVE_WORKING", "COMPLETED", "AWAITING_USER"}
        if classification in valid_categories:
            print(f"[PanelTracker] Classified panel output as: {classification}")
            return classification
        print(f"[PanelTracker] Unexpected classification: {classification}, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"
    except Exception as e:
        print(f"[PanelTracker] Error classifying panel output: {e}, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"


def check_output_for_next_steps(output_text: str) -> bool:
    lower = output_text.lower()
    return "next steps" in lower or "next step" in lower


def check_output_for_task_completed(output_text: str) -> bool:
    return "task completed" in output_text.lower()


def is_prompt_generator_panel(output_text: str) -> bool:
    lower = output_text.lower()
    return "prompt" in lower or "agent" in lower


# ---------------------------------------------------------------------------
# Public orchestration APIs
# ---------------------------------------------------------------------------


def process_finished_panels_with_prompts(vs_windows: List["auto.Control"]) -> int:
    """Drive finished panels: keep edits, open new chat, seed prompt batch."""
    tracker = get_tracker()
    return _panel_seeding.process_finished_panels_with_prompts(tracker, vs_windows)


def process_finished_panels(vs_windows: List["auto.Control"]) -> int:
    """Send follow-up prompts to finished panels (legacy API)."""
    from automation import panel_followups as _panel_followups

    tracker = get_tracker()
    return _panel_followups.process_finished_panels(tracker, vs_windows)


def update_panel_from_window(vs_win: "auto.Control", panel_id: str = "") -> None:
    """Update tracker state from a VS Code window control (legacy API)."""
    try:
        window_title = vs_win.Name or "Unknown"
    except Exception:
        window_title = "Unknown"

    try:
        output_text = get_panel_output_text(vs_win)
    except Exception:
        output_text = ""

    try:
        is_running = detect_panel_running_state(vs_win)
    except Exception:
        is_running = False

    get_tracker().update_panel_output(window_title, output_text, is_running=is_running, panel_id=panel_id)


def process_rate_limited_panels(vs_windows: List["auto.Control"]) -> int:
    """Send 'please continue' to panels stuck rate-limited without a button."""
    if not ENABLE_SEND_TO_INACTIVE_PANELS:
        return 0

    tracker = get_tracker()
    processed = 0

    window_map: Dict[str, "auto.Control"] = {}
    for vs_win in vs_windows:
        try:
            title = vs_win.Name or ""
            if title:
                window_map[title] = vs_win
        except Exception:
            pass

    for panel in tracker.panels.values():
        if panel.idle_reason != IdleReason.RATE_LIMITED_NO_BUTTON:
            continue
        if panel.sent_please_continue:
            continue

        vs_win = window_map.get(panel.window_title)
        if vs_win is None:
            continue

        try:
            output_text = get_panel_output_text(vs_win)
            if is_prompt_generator_panel(output_text):
                print(f"[PanelTracker] Skipping prompt generator (rate limited): {panel.window_title[:50]}")
                panel.status = PanelStatus.COMPLETED
                tracker._save_state()
                continue

            print(
                f"\n[PanelTracker] Rate limited (no button) - sending 'please continue': {panel.window_title[:50]}"
            )
            if send_text_to_chat(vs_win, PLEASE_CONTINUE_PROMPT):
                panel.sent_please_continue = True
                panel.last_allow_click = _panel_seeding.datetime.now()
                processed += 1
                tracker._save_state()
        except Exception as e:
            print(f"[PanelTracker] Error sending 'please continue': {e}")

    return processed


def check_for_task_completed(vs_win: "auto.Control") -> bool:
    """Check if a panel's output indicates task completion."""
    tracker = get_tracker()

    try:
        window_title = vs_win.Name or "Unknown"
        output_text = get_panel_output_text(vs_win)
        if check_output_for_task_completed(output_text):
            tracker.mark_completed(window_title, completion_text=output_text)
            return True
    except Exception as e:
        print(f"[PanelTracker] Error checking for task completed: {e}")

    return False


def get_window_priority(window_title: str) -> int:
    """Return processing priority for a window based on panel status."""
    return get_tracker().get_panel_priority(window_title)


def print_tracker_status() -> None:
    get_tracker().print_status_summary()


def should_check_finished_panels(remaining_clicks: int, live_panels_found: bool) -> bool:
    if live_panels_found:
        return False
    finished = get_tracker().get_finished_panels()
    if not finished:
        return False
    return remaining_clicks > 0
