"""Tests verifying parser integration with panel tracker."""

from __future__ import annotations

import datetime
import hashlib

import automation.panel_tracker as pt
from automation.response_parser import ResponseCategory


def _build_tracker(monkeypatch) -> pt.PanelTracker:
    monkeypatch.setattr(pt.PanelTracker, "_load_state", lambda self: None)
    monkeypatch.setattr(pt.PanelTracker, "_save_state", lambda self: None)
    return pt.PanelTracker()


def test_parser_marks_needs_input(monkeypatch) -> None:
    tracker = _build_tracker(monkeypatch)
    now = datetime.datetime.now()
    panel = pt.PanelState(
        window_title="Clarification Panel - Visual Studio Code",
        panel_id="panel-clarify",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        last_scanned=now,
        last_output_sample="initial",
        last_output_hash=hashlib.sha256(b"old").hexdigest()[:16],
        status=pt.PanelStatus.IDLE,
    )
    tracker.panels[tracker._generate_panel_key(panel.window_title, panel.panel_id)] = panel

    tracker.update_panel_output(
        window_title=panel.window_title,
        output_text="I need the file path to continue",
        is_running=False,
        panel_id=panel.panel_id,
    )

    assert panel.status == pt.PanelStatus.NEEDS_INPUT
    assert panel.idle_reason == pt.IdleReason.AWAITING_USER
    assert panel.last_response_category == ResponseCategory.ASKING_CLARIFICATION


def test_finished_panels_honor_parser_suggestions(monkeypatch) -> None:
    tracker = _build_tracker(monkeypatch)
    now = datetime.datetime.now()
    panel = pt.PanelState(
        window_title="Finished Panel - Visual Studio Code",
        panel_id="panel-finished",
        first_seen=now,
        last_allow_click=now - datetime.timedelta(minutes=90),
        last_output_change=now - datetime.timedelta(minutes=90),
        last_scanned=now - datetime.timedelta(minutes=45),
        last_output_sample="Next steps: wrap up and commit",
        last_output_hash=hashlib.sha256(b"done").hexdigest()[:16],
        status=pt.PanelStatus.FINISHED,
        sent_completion_check=True,
        sent_next_steps_response=False,
        last_response_category=ResponseCategory.SUGGESTING_NEXT_STEPS,
    )
    tracker.panels[tracker._generate_panel_key(panel.window_title, panel.panel_id)] = panel

    attention = tracker.get_finished_panels_needing_attention()
    assert panel in attention


def test_panel_tracks_secondary_categories(monkeypatch) -> None:
    tracker = _build_tracker(monkeypatch)
    now = datetime.datetime.now()
    panel = pt.PanelState(
        window_title="Multi-signal Panel - Visual Studio Code",
        panel_id="panel-secondary",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        last_scanned=now,
        last_output_sample="initial",
        last_output_hash=hashlib.sha256(b"initial").hexdigest()[:16],
        status=pt.PanelStatus.IDLE,
    )
    tracker.panels[tracker._generate_panel_key(panel.window_title, panel.panel_id)] = panel

    tracker.update_panel_output(
        window_title=panel.window_title,
        output_text="Next steps: deploy. Also, please provide the config file.",
        is_running=False,
        panel_id=panel.panel_id,
    )

    assert panel.last_response_category == ResponseCategory.ASKING_CLARIFICATION
    assert ResponseCategory.SUGGESTING_NEXT_STEPS in panel.last_response_secondary_categories
