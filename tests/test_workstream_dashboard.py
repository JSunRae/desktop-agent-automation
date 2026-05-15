from __future__ import annotations

from automation.workstream_coordination import WorkstreamRecord
from scripts.workstream_dashboard import build_dashboard_summary


def test_build_dashboard_summary_counts_lifecycle_and_limits():
    records = [
        WorkstreamRecord(
            workstream_id="repo:task-a:123",
            repo_name="desktop-agent-automation",
            task_name="Task A",
            active_panel_ids=["p1", "p2"],
            statuses=["running", "finished"],
            issue_tags=[],
            estimated_context_tokens=12000,
            active_panel_count=2,
            condensation_count=3,
            fresh_chat_count=1,
            reuse_count=2,
        ),
        WorkstreamRecord(
            workstream_id="repo:task-b:456",
            repo_name="desktop-agent-automation",
            task_name="Task B",
            active_panel_ids=["p3"],
            statuses=["finished"],
            issue_tags=["test_failure"],
            estimated_context_tokens=3000,
            active_panel_count=1,
            condensation_count=0,
            fresh_chat_count=2,
            reuse_count=0,
        ),
    ]

    summary = build_dashboard_summary(records)

    assert summary["total_workstreams"] == 2
    assert summary["active_workstreams"] == 2
    assert summary["total_panels"] == 3
    assert summary["flagged_workstreams"] == 1
    assert summary["multi_panel_workstreams"] == 1
    assert summary["over_soft_limit"] >= 1
    assert summary["lifecycle_totals"] == {
        "reuse_existing": 2,
        "condense_to_fresh": 3,
        "start_fresh": 3,
    }


def test_build_dashboard_summary_recommends_fresh_for_severe_issue():
    records = [
        WorkstreamRecord(
            workstream_id="repo:task-c:789",
            repo_name="desktop-agent-automation",
            task_name="Task C",
            active_panel_ids=["p1"],
            statuses=["finished"],
            issue_tags=["merge_conflict"],
            estimated_context_tokens=100,
            active_panel_count=1,
        )
    ]

    summary = build_dashboard_summary(records)

    assert summary["rows"][0]["recommended_action"] == "start_fresh"


def test_build_dashboard_summary_counts_panels_without_panel_ids():
    records = [
        WorkstreamRecord(
            workstream_id="repo:task-d:111",
            repo_name="desktop-agent-automation",
            task_name="Task D",
            panel_titles=["Panel One", "Panel Two"],
            statuses=["stale", "finished"],
            estimated_context_tokens=200,
            active_panel_count=0,
        )
    ]

    summary = build_dashboard_summary(records)

    assert summary["total_panels"] == 2
    assert summary["rows"][0]["panel_count"] == 2