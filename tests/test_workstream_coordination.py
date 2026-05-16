from __future__ import annotations

import datetime as dt

from automation.panel_state import (
    TRANSCRIPT_KIND_SEED_PROMPT,
    PanelState,
    PanelStatus,
    TranscriptSnapshot,
)
from automation.workstream_coordination import (
    ChatLifecycleAction,
    WorkstreamCoordinator,
)


def _make_panel(*, title: str = "Repo Task - desktop-agent-automation", task_id: str = "repo:task-1", issue_tags=None) -> PanelState:
    now = dt.datetime(2026, 4, 27, 12, 0, 0)
    panel = PanelState(
        window_title=title,
        panel_id="panel-1",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        last_scanned=now,
        last_allow_check=now,
        status=PanelStatus.FINISHED,
        repo_name="desktop-agent-automation",
        assigned_task_id=task_id,
        assigned_task_name="Investigate token budget policy",
        assigned_prompt_text="Inspect token budget signals and summarize findings.",
        last_output_sample="Reviewed panel state and prompt routing.",
        transcript_issue_tags=list(issue_tags or []),
        transcript_issue_summary="Panel finished cleanly.",
    )
    return panel


def test_workstream_policy_reuses_when_under_budget(tmp_path):
    panel = _make_panel()
    panel.transcript_snapshots.append(
        TranscriptSnapshot(
            kind=TRANSCRIPT_KIND_SEED_PROMPT,
            timestamp=dt.datetime(2026, 4, 27, 12, 5, 0),
            content_hash="abc123def456",
            preview="Short prompt",
            filtered=False,
            length=40,
        )
    )
    coordinator = WorkstreamCoordinator(state_path=tmp_path / "workstreams.json")

    decision = coordinator.decide_for_panel(panel, "Continue with small follow-up.", [panel])

    assert decision.action == ChatLifecycleAction.REUSE_EXISTING
    assert decision.rendered_prompt == "Continue with small follow-up."
    assert decision.estimated_context_tokens > 0


def test_workstream_policy_condenses_when_over_budget(tmp_path):
    panel = _make_panel()
    for index in range(4):
        panel.transcript_snapshots.append(
            TranscriptSnapshot(
                kind=TRANSCRIPT_KIND_SEED_PROMPT,
                timestamp=dt.datetime(2026, 4, 27, 12, index, 0),
                content_hash=f"hash-{index}",
                preview="Large prompt preview",
                filtered=False,
                length=8000,
            )
        )
    coordinator = WorkstreamCoordinator(state_path=tmp_path / "workstreams.json")

    decision = coordinator.decide_for_panel(panel, "Continue with another repo sync.", [panel])

    assert decision.action == ChatLifecycleAction.CONDENSE_TO_FRESH
    assert "Workstream handoff summary" in decision.rendered_prompt
    assert "Current assignment:" in decision.rendered_prompt


def test_workstream_policy_starts_fresh_on_severe_issue(tmp_path):
    panel = _make_panel(issue_tags=["test_failure"])
    panel.transcript_snapshots.append(
        TranscriptSnapshot(
            kind=TRANSCRIPT_KIND_SEED_PROMPT,
            timestamp=dt.datetime(2026, 4, 27, 12, 5, 0),
            content_hash="severe123456",
            preview="Debug failing test suite",
            filtered=False,
            length=400,
        )
    )
    coordinator = WorkstreamCoordinator(state_path=tmp_path / "workstreams.json")

    decision = coordinator.decide_for_panel(panel, "Restart from a clean state.", [panel])

    assert decision.action == ChatLifecycleAction.START_FRESH
    assert decision.rendered_prompt == "Restart from a clean state."


def test_workstream_coordinator_honors_env_override(monkeypatch, tmp_path):
    override_path = tmp_path / "workstream_coordination.json"
    monkeypatch.setenv("WORKSTREAM_COORDINATION_STATE_PATH", str(override_path))

    coordinator = WorkstreamCoordinator()

    assert coordinator.state_path == override_path
