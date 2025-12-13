"""Finished panel completion review helpers.

Currently not wired into the main seeding flow, but kept for parity with the
previous monolithic `panel_tracker.py` implementation.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, List, Optional, TYPE_CHECKING, cast

from automation.config import (
    FINISHED_PANEL_REVIEW_BACKOFF_SECONDS,
    FINISHED_PANEL_REVIEW_MAX_RETRIES,
    FINISHED_PANEL_REVIEW_MODEL,
    FINISHED_PANEL_REVIEW_TEMPERATURE,
    FINISHED_PANEL_REVIEW_TRANSCRIPT_CHARS,
)
from automation.cost_tracker import get_cost_tracker
from automation.panel_state import (
    PanelState,
    TRANSCRIPT_FILTER_PLACEHOLDER,
    TRANSCRIPT_KIND_REVIEW,
    TRANSCRIPT_KIND_SEED_PROMPT,
    TRANSCRIPT_MAX_SNAPSHOTS,
    extract_repo_name_from_title,
)
from automation.panel_ui import get_panel_output_text, send_text_to_chat
from automation.panel_tracker_core import PanelTracker

if TYPE_CHECKING:
    import uiautomation as auto


openai_module: Any
try:
    import openai as _openai_module
except ImportError:
    _openai_module = cast(Any, None)
openai_module = _openai_module


REVIEW_ACTION_FOLLOW_UP = "follow_up"
REVIEW_ACTION_CLARIFY = "clarify"
REVIEW_ACTION_OK = "ok"
REVIEW_ACTIONS = {
    REVIEW_ACTION_FOLLOW_UP,
    REVIEW_ACTION_CLARIFY,
    REVIEW_ACTION_OK,
}


@dataclass
class PanelReviewDecision:
    """Structured directive returned by the completion review model."""

    action: str
    message: str
    source: str = "model"
    raw_response: Optional[str] = None


REVIEW_SYSTEM_PROMPT = dedent(
    """You are GPT-5.1 Codex acting as a completion reviewer for Copilot chat panels.
Evaluate the supplied seed prompt context, transcript excerpt, and timeline to decide
how to close the conversation before reseeding the panel.

Respond with JSON matching this schema:
{
  \"action\": \"follow_up\" | \"clarify\" | \"ok\",
  \"message\": \"short text (<=200 chars) to send\"
}

- follow_up: Provide a short wrap-up note or recommended follow-up text.
- clarify: Ask for missing info required to finish the task.
- ok: Acknowledge completion with \"ok\" if no extra work is required.

Never include markdown fences. Keep the message concise and actionable.
"""
)


def _truncate_text(value: str, limit: int) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return f"{trimmed[: limit - 3]}..."


def _seed_prompt_context(panel: PanelState) -> str:
    if panel.last_seed_prompt_text:
        return panel.last_seed_prompt_text.strip()
    if panel.assigned_prompt_text:
        return panel.assigned_prompt_text.strip()
    snapshots = getattr(panel, "transcript_snapshots", []) or []
    for snapshot in reversed(snapshots):
        if snapshot.kind == TRANSCRIPT_KIND_SEED_PROMPT:
            if snapshot.filtered:
                return TRANSCRIPT_FILTER_PLACEHOLDER
            if snapshot.preview:
                return snapshot.preview
    return ""


def _summarize_snapshots(panel: PanelState) -> str:
    if not panel.transcript_snapshots:
        return "(none recorded)"
    lines: List[str] = []
    for snapshot in panel.transcript_snapshots[-TRANSCRIPT_MAX_SNAPSHOTS:]:
        label = snapshot.preview or (TRANSCRIPT_FILTER_PLACEHOLDER if snapshot.filtered else "(no preview)")
        lines.append(f"{snapshot.kind}@{snapshot.timestamp.isoformat()}: {label}")
    return "\n".join(lines)


def _build_review_prompt(panel: PanelState, transcript_excerpt: str) -> str:
    prompt_excerpt = _truncate_text(_seed_prompt_context(panel), FINISHED_PANEL_REVIEW_TRANSCRIPT_CHARS) or "(missing seed prompt)"
    transcript_section = transcript_excerpt or (panel.last_output_sample or "(no transcript captured)")
    snapshot_summary = _summarize_snapshots(panel)
    assignment = panel.assigned_task_name or panel.assigned_task_id or "unspecified-task"
    repo = panel.repo_name or extract_repo_name_from_title(panel.window_title) or "unknown-repo"
    return dedent(
        f"""
        Panel title: {panel.window_title}
        Repository: {repo}
        Assignment: {assignment}

        Seed prompt excerpt:
        {prompt_excerpt}

        Transcript excerpt:
        {transcript_section}

        Snapshot timeline:
        {snapshot_summary}

        Pick the directive before reseeding this panel.
        """
    ).strip()


def _parse_review_decision(raw_text: str) -> PanelReviewDecision:
    fallback = PanelReviewDecision(action=REVIEW_ACTION_OK, message="ok", source="fallback", raw_response=raw_text)
    if not raw_text:
        return fallback
    text = raw_text.strip()
    payload: Any = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"{.*}", text, re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None

    action = ""
    message = ""
    if isinstance(payload, dict):
        action = str(payload.get("action", "")).strip().lower()
        message = str(payload.get("message", "")).strip()

    if not action:
        lowered = text.lower()
        if "clarify" in lowered:
            action = REVIEW_ACTION_CLARIFY
        elif "follow" in lowered:
            action = REVIEW_ACTION_FOLLOW_UP
        else:
            action = REVIEW_ACTION_OK
        if not message:
            message = text

    if action not in REVIEW_ACTIONS:
        action = REVIEW_ACTION_OK
    if action == REVIEW_ACTION_OK and not message:
        message = "ok"

    return PanelReviewDecision(action=action, message=message[:200], source="model", raw_response=raw_text)


def _gather_transcript_excerpt(panel: PanelState, vs_win: "auto.Control") -> str:
    transcript = ""
    try:
        transcript = get_panel_output_text(vs_win)
    except Exception as exc:
        print(f"[PanelTracker] Unable to read transcript for {panel.window_title[:50]}: {exc}")
    if not transcript:
        transcript = panel.last_output_sample or ""
    return _truncate_text(transcript, FINISHED_PANEL_REVIEW_TRANSCRIPT_CHARS)


def request_review_decision(panel: PanelState, vs_win: "auto.Control") -> Optional[PanelReviewDecision]:
    if openai_module is None:
        return None

    import os

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    transcript_excerpt = _gather_transcript_excerpt(panel, vs_win)
    prompt_body = _build_review_prompt(panel, transcript_excerpt)
    client = openai_module.OpenAI(api_key=api_key)

    backoff = max(FINISHED_PANEL_REVIEW_BACKOFF_SECONDS, 0.2)
    last_error: Optional[str] = None

    for attempt in range(FINISHED_PANEL_REVIEW_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=FINISHED_PANEL_REVIEW_MODEL,
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_body},
                ],
                temperature=FINISHED_PANEL_REVIEW_TEMPERATURE,
                max_tokens=200,
            )
            raw_text = (response.choices[0].message.content or "").strip()
            decision = _parse_review_decision(raw_text)

            usage = getattr(response, "usage", None)
            cost_tracker = get_cost_tracker()
            cost_tracker.record_text_usage(
                source="panel_tracker",
                event="finished_panel_review",
                model=FINISHED_PANEL_REVIEW_MODEL,
                usage=usage,
                details={
                    "decision_action": decision.action,
                    "panel": panel.window_title[:60],
                    "assignment": panel.assigned_task_id,
                },
            )

            return decision
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
            if attempt < FINISHED_PANEL_REVIEW_MAX_RETRIES - 1:
                time.sleep(backoff * (attempt + 1))

    if last_error:
        print(f"[PanelTracker] Review model unavailable for {panel.window_title[:50]}: {last_error}")
    return None


def _handle_review_decision(tracker: PanelTracker, panel: PanelState, vs_win: "auto.Control", decision: PanelReviewDecision) -> bool:
    message = (decision.message or "").strip()
    if decision.action == REVIEW_ACTION_OK and not message:
        message = "ok"
    if not message:
        return True

    sent = send_text_to_chat(vs_win, message)
    if sent:
        tracker._record_transcript_snapshot(panel, kind=TRANSCRIPT_KIND_REVIEW, text=message)
        tracker._save_state()
        return True

    print(f"[PanelTracker] Failed to send review directive for {panel.window_title[:50]}")
    return False


def conduct_finished_panel_review(tracker: PanelTracker, panel: PanelState, vs_win: "auto.Control") -> bool:
    decision = request_review_decision(panel, vs_win)
    if decision is None:
        decision = PanelReviewDecision(action=REVIEW_ACTION_OK, message="ok", source="fallback", raw_response=None)

    panel.last_review_action = decision.action
    panel.last_review_message = decision.message
    print(f"[PanelTracker] Review decision for {panel.window_title[:50]} -> {decision.action}")

    return _handle_review_decision(tracker, panel, vs_win, decision)
