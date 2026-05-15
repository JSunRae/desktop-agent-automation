"""Regression tests for PanelState transcript persistence."""
from __future__ import annotations

import datetime as dt

import automation.panel_tracker as pt


def _make_panel_state() -> pt.PanelState:
    now = dt.datetime(2025, 1, 1, 12, 0, 0)
    return pt.PanelState(
        window_title="Test Panel - Repo",
        panel_id="panel-1",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        last_scanned=now,
        last_allow_check=now,
    )


def test_panel_state_round_trip_without_transcripts():
    panel = _make_panel_state()
    serialized = panel.to_dict()
    serialized.pop("transcript_snapshots", None)

    restored = pt.PanelState.from_dict(serialized)

    assert restored.window_title == panel.window_title
    assert restored.transcript_snapshots == []


def test_panel_state_round_trip_with_transcripts():
    panel = _make_panel_state()
    panel.workstream_id = "repo:task:abc123"
    panel.estimated_context_tokens = 128
    panel.last_chat_action = "condense_to_fresh"
    panel.last_chat_action_reason = "Estimated context exceeded threshold"
    snapshot = pt.TranscriptSnapshot(
        kind=pt.TRANSCRIPT_KIND_SEED_PROMPT,
        timestamp=dt.datetime(2025, 1, 1, 13, 0, 0),
        content_hash="abc123def456",
        preview="Seed prompt preview",
        filtered=False,
        length=21,
    )
    panel.transcript_snapshots.append(snapshot)

    restored = pt.PanelState.from_dict(panel.to_dict())

    assert len(restored.transcript_snapshots) == 1
    restored_snapshot = restored.transcript_snapshots[0]
    assert restored_snapshot.kind == snapshot.kind
    assert restored_snapshot.content_hash == snapshot.content_hash
    assert restored_snapshot.preview == snapshot.preview
    assert restored_snapshot.filtered is False
    assert restored.workstream_id == panel.workstream_id
    assert restored.estimated_context_tokens == 128
    assert restored.last_chat_action == "condense_to_fresh"
    assert restored.last_chat_action_reason == "Estimated context exceeded threshold"


def test_tracker_records_transcript_snapshots(monkeypatch):
    monkeypatch.setattr(pt.PanelTracker, "_load_state", lambda self: None)
    monkeypatch.setattr(pt.PanelTracker, "_save_state", lambda self: None)
    tracker = pt.PanelTracker()

    panel = _make_panel_state()
    tracker.panels[tracker._generate_panel_key(panel.window_title, panel.panel_id)] = panel

    tracker._record_transcript_snapshot(panel, kind=pt.TRANSCRIPT_KIND_COMPLETION, text="Normal output")
    assert len(panel.transcript_snapshots) == 1
    assert panel.transcript_snapshots[0].filtered is False

    tracker._record_transcript_snapshot(panel, kind=pt.TRANSCRIPT_KIND_COMPLETION, text="Normal output")
    assert len(panel.transcript_snapshots) == 1, "Duplicate completion text should not duplicate snapshots"

    tracker._record_transcript_snapshot(panel, kind=pt.TRANSCRIPT_KIND_COMPLETION, text="password: secret")
    assert panel.transcript_snapshots[-1].filtered is True
    assert panel.transcript_snapshots[-1].preview == pt.TRANSCRIPT_FILTER_PLACEHOLDER

    for idx in range(pt.TRANSCRIPT_MAX_SNAPSHOTS + 2):
        tracker._record_transcript_snapshot(panel, kind=pt.TRANSCRIPT_KIND_SEED_PROMPT, text=f"Prompt {idx}")

    assert len(panel.transcript_snapshots) == pt.TRANSCRIPT_MAX_SNAPSHOTS