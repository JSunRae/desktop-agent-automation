#!/usr/bin/env python3
"""Panel quality dashboard and weekly report generator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.panel_quality import get_panel_quality_analyzer
from automation.panel_state import PanelState
from automation.panel_tracker_core import DEFAULT_PANEL_STATE_PATH, PanelTracker


def _load_panels(state_path: Path) -> List[PanelState]:
    tracker = PanelTracker(state_path=state_path)
    return list(tracker.panels.values())


def _ensure_assessments(panels: Iterable[PanelState], analyzer) -> None:
    for panel in panels:
        if panel.quality_assessment:
            continue
        transcript = panel.last_output_sample or ""
        analyzer.evaluate_panel(panel, transcript, panel.assigned_prompt_text)


def _render_dashboard(summary: dict) -> None:
    print("\n=== Panel Quality Dashboard ===")
    print(f"Generated: {summary['generated_at']}")
    print(f"Total panels: {summary['total_panels']} | Needs review: {summary['needs_review']}")
    print(f"Average quality score: {summary['average_score']:.3f}")
    trend = summary.get("trend", {})
    if trend:
        print(
            "Weekly completion rate: "
            f"{trend.get('weekly_completion_rate', 0.0):.3f} (samples={trend.get('history_samples', 0)})"
        )
    print("Status breakdown:")
    status_breakdown = summary.get("status_breakdown", {})
    for name, count in sorted(status_breakdown.items()):
        print(f"  - {name}: {count}")

    alerts = summary.get("quality_alerts") or []
    if alerts:
        print("\nAlerts:")
        for alert in alerts:
            print(f"  * {alert}")

    concerns = summary.get("quality_concerns") or []
    if concerns:
        print("\nTop quality concerns:")
        for concern in concerns:
            print(f"  - {concern}")

    rows = summary.get("rows", [])
    if rows:
        print("\nPanels needing attention:")
        for idx, row in enumerate(rows, start=1):
            status = row.get("status", "UNKNOWN")
            score = row.get("score", 0.0)
            panel_name = row.get("panel")
            flags = ", ".join(row.get("flags", []))
            issues = ", ".join(row.get("issues", []))
            print(f"{idx:2}. [{status}] {panel_name} | score={score:.3f}")
            if issues:
                print(f"    Issues: {issues}")
            if flags:
                print(f"    Flags: {flags}")
            if row.get("task"):
                print(f"    Task: {row['task']}")
            if row.get("needs_review"):
                print("    [!] Requires human review")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the panel quality dashboard")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_PANEL_STATE_PATH,
        help="Path to panel_state.json (defaults to automation/panel_state.json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON instead of a formatted table",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum panels to display",
    )
    parser.add_argument(
        "--weekly-report",
        action="store_true",
        help="Generate and persist the weekly quality report",
    )
    args = parser.parse_args()

    panels = _load_panels(args.state_path)
    analyzer = get_panel_quality_analyzer()
    _ensure_assessments(panels, analyzer)

    summary = analyzer.build_dashboard_summary(panels)
    if args.limit:
        summary["rows"] = summary.get("rows", [])[: args.limit]

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _render_dashboard(summary)

    if args.weekly_report:
        report = analyzer.generate_weekly_report(panels)
        if not args.json:
            print(
                "\nSaved weekly report window "
                f"{report['window_start']} -> {report['window_end']} (entries={report['entry_count']})"
            )


if __name__ == "__main__":
    main()
