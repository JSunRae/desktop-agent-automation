#!/usr/bin/env python3
"""Render a workstream lifecycle dashboard from panel and coordinator state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.panel_tracker_core import DEFAULT_PANEL_STATE_PATH, PanelTracker
from automation.workstream_coordination import (
    DEFAULT_WORKSTREAM_STATE_PATH,
    WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT,
    WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT,
    WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT,
    WorkstreamCoordinator,
    WorkstreamRecord,
)


def _load_workstreams(*, state_path: Path, workstream_state_path: Path) -> List[WorkstreamRecord]:
    tracker = PanelTracker(state_path=state_path)
    coordinator = WorkstreamCoordinator(state_path=workstream_state_path)
    records = coordinator.sync_panels(tracker.panels.values())
    return sorted(
        records.values(),
        key=lambda record: (
            record.estimated_context_tokens,
            record.active_panel_count,
            record.condensation_count + record.fresh_chat_count + record.reuse_count,
            record.last_updated,
        ),
        reverse=True,
    )


def _recommended_action(record: WorkstreamRecord) -> str:
    severe_tags = {"merge_conflict", "test_failure", "error_output"}
    if severe_tags.intersection(record.issue_tags):
        return "start_fresh"
    if record.estimated_context_tokens >= WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT:
        return "condense_now"
    if record.active_panel_count > 1 and record.estimated_context_tokens >= WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT:
        return "condense_multi_panel"
    if record.estimated_context_tokens >= WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT:
        return "condense_soon"
    return "reuse_existing"


def _panel_count(record: WorkstreamRecord) -> int:
    return max(
        len(record.active_panel_ids),
        len(record.panel_titles),
        len(record.statuses),
        record.active_panel_count,
    )


def build_dashboard_summary(records: Iterable[WorkstreamRecord], *, limit: int | None = None) -> dict:
    rows = []
    records = list(records)
    total_panels = sum(_panel_count(record) for record in records)
    active_workstreams = sum(1 for record in records if record.active_panel_count > 0)
    flagged_workstreams = sum(1 for record in records if record.issue_tags)
    over_soft_limit = sum(1 for record in records if record.estimated_context_tokens >= WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT)
    over_hard_limit = sum(1 for record in records if record.estimated_context_tokens >= WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT)
    multi_panel_workstreams = sum(1 for record in records if record.active_panel_count > 1)
    lifecycle_totals = {
        "reuse_existing": sum(record.reuse_count for record in records),
        "condense_to_fresh": sum(record.condensation_count for record in records),
        "start_fresh": sum(record.fresh_chat_count for record in records),
    }

    for record in records:
        row = {
            "workstream_id": record.workstream_id,
            "repo_name": record.repo_name,
            "task_name": record.task_name,
            "active_panel_count": record.active_panel_count,
            "panel_count": _panel_count(record),
            "estimated_context_tokens": record.estimated_context_tokens,
            "statuses": list(record.statuses),
            "issue_tags": list(record.issue_tags),
            "summary": record.summary,
            "latest_output_preview": record.latest_output_preview,
            "last_action": record.last_action,
            "last_action_reason": record.last_action_reason,
            "condensation_count": record.condensation_count,
            "fresh_chat_count": record.fresh_chat_count,
            "reuse_count": record.reuse_count,
            "last_updated": record.last_updated,
            "recommended_action": _recommended_action(record),
        }
        rows.append(row)

    if limit and limit > 0:
        rows = rows[:limit]

    return {
        "total_workstreams": len(records),
        "active_workstreams": active_workstreams,
        "total_panels": total_panels,
        "flagged_workstreams": flagged_workstreams,
        "multi_panel_workstreams": multi_panel_workstreams,
        "over_soft_limit": over_soft_limit,
        "over_hard_limit": over_hard_limit,
        "soft_limit": WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT,
        "hard_limit": WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT,
        "multi_panel_limit": WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT,
        "lifecycle_totals": lifecycle_totals,
        "rows": rows,
    }


def _render_dashboard(summary: dict) -> None:
    print("\n=== Workstream Dashboard ===")
    print(
        "Workstreams: "
        f"{summary['total_workstreams']} total | {summary['active_workstreams']} active | "
        f"{summary['flagged_workstreams']} flagged | {summary['multi_panel_workstreams']} multi-panel"
    )
    print(
        "Context limits: "
        f"{summary['over_soft_limit']} over soft ({summary['soft_limit']}) | "
        f"{summary['over_hard_limit']} over hard ({summary['hard_limit']})"
    )
    lifecycle = summary["lifecycle_totals"]
    print(
        "Lifecycle totals: "
        f"reuse={lifecycle['reuse_existing']} | "
        f"condense={lifecycle['condense_to_fresh']} | "
        f"fresh={lifecycle['start_fresh']}"
    )

    rows = summary.get("rows", [])
    if not rows:
        print("No workstream records found.")
        return

    print("\nTop workstreams:")
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:2}. [{row['repo_name']}] {row['task_name']} | "
            f"tokens={row['estimated_context_tokens']} | "
            f"active={row['active_panel_count']}/{row['panel_count']} | "
            f"next={row['recommended_action']}"
        )
        if row.get("last_action"):
            print(f"    Last action: {row['last_action']} ({row.get('last_action_reason') or 'no reason recorded'})")
        if row.get("issue_tags"):
            print(f"    Issue tags: {', '.join(row['issue_tags'])}")
        if row.get("summary"):
            print(f"    Summary: {row['summary']}")
        if row.get("latest_output_preview"):
            print(f"    Output: {row['latest_output_preview']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the workstream lifecycle dashboard")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_PANEL_STATE_PATH,
        help="Path to panel_state.json (defaults to automation/panel_state.json)",
    )
    parser.add_argument(
        "--workstream-state-path",
        type=Path,
        default=DEFAULT_WORKSTREAM_STATE_PATH,
        help="Path to workstream_coordination.json (defaults to state/workstream_coordination.json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON instead of a formatted dashboard",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum workstreams to display",
    )
    args = parser.parse_args()

    records = _load_workstreams(state_path=args.state_path, workstream_state_path=args.workstream_state_path)
    summary = build_dashboard_summary(records, limit=args.limit)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _render_dashboard(summary)


if __name__ == "__main__":
    main()
