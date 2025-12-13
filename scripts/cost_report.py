"""CLI for the financial tracking and optimization system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from automation.cost_analytics import CostAnalytics  # noqa: E402
from automation.cost_tracker import DEFAULT_COST_METRICS_PATH  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate OpenAI spend analytics")
    parser.add_argument("--days", type=int, default=45, help="Number of days to analyze (default: 45)")
    parser.add_argument("--panel-limit", type=int, default=10, help="Rows to show in the panel cost table")
    parser.add_argument("--repo-limit", type=int, default=10, help="Rows to show in the repo cost table")
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=DEFAULT_COST_METRICS_PATH,
        help="Override path to logs/cost_metrics.jsonl",
    )
    parser.add_argument("--json", action="store_true", help="Emit the raw analytics payload as JSON")
    return parser


def format_currency(value: float) -> str:
    return f"${value:,.4f}"


def render_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    rows_list: List[List[str]] = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in rows_list:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    header_line = " | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))
    divider = "-+-".join("-" * width for width in widths)
    print(header_line)
    print(divider)
    for row in rows_list:
        print(" | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)))


def print_agent_spend(agent_spend: dict) -> None:
    for label in ("daily", "weekly", "monthly"):
        entries = agent_spend.get(label) or []
        if not entries:
            continue
        print(f"\nAgent spend by {label}")
        rows = []
        headers = ["Period", "Auto-Allow", "Master Orchestrator", "Other", "Total"]
        for entry in entries:
            breakdown = entry.get("agent_breakdown", {})
            rows.append(
                [
                    entry.get("period", ""),
                    format_currency(breakdown.get(CostAnalytics.AUTO_ALLOW_LABEL, 0.0)),
                    format_currency(breakdown.get(CostAnalytics.ORCHESTRATOR_LABEL, 0.0)),
                    format_currency(breakdown.get(CostAnalytics.OTHER_LABEL, 0.0)),
                    format_currency(entry.get("total_cost", 0.0)),
                ]
            )
        render_table(headers, rows)


def print_cost_table(title: str, rows: List[dict]) -> None:
    if not rows:
        return
    print(f"\n{title}")
    table_rows = [
        [row.get("label", row.get("model", "")), str(row.get("calls", 0)), format_currency(row.get("cost", 0.0)), format_currency(row.get("avg_cost_per_call", 0.0))]
        for row in rows
    ]
    render_table(["Label", "Calls", "Cost", "Avg/Call"], table_rows)


def print_model_distribution(rows: List[dict]) -> None:
    if not rows:
        return
    print("\nModel usage distribution")
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                row.get("model", ""),
                str(row.get("calls", 0)),
                format_currency(row.get("cost", 0.0)),
                f"{row.get('avg_input_tokens', 0):.0f}",
                f"{row.get('avg_output_tokens', 0):.0f}",
            ]
        )
    render_table(["Model", "Calls", "Cost", "Avg Input", "Avg Output"], table_rows)


def describe_trend(trend: dict) -> None:
    if not trend:
        print("\nTrend analysis unavailable (insufficient data).")
        return
    print("\nTrend analysis")
    avg_cost = trend.get("avg_daily_cost", 0.0)
    change = trend.get("seven_day_change_pct")
    line = f"Average daily cost: {format_currency(avg_cost)}"
    if isinstance(change, float):
        line += f" | 7-day delta: {change:+.1%}"
    line += f" | Direction: {trend.get('trend_direction', 'flat')}"
    print(line)


def describe_outliers(outliers: List[dict]) -> None:
    if not outliers:
        print("\nNo daily spend outliers detected.")
        return
    print("\nDaily spend outliers")
    rows = [
        [entry.get("period", ""), format_currency(entry.get("cost", 0.0)), f"{entry.get('z_score', 0.0):.2f}"]
        for entry in outliers
    ]
    render_table(["Period", "Cost", "Z-score"], rows)


def print_recommendations(recommendations: List[str]) -> None:
    print("\nOptimization recommendations")
    for rec in recommendations:
        print(f"- {rec}")


def print_report(report: dict) -> None:
    if report.get("records_analyzed", 0) == 0:
        print("No OpenAI cost data available. Try running the automation first or extend --days.")
        return
    print("OPENAI COST REPORT")
    print("===================")
    print(
        f"Records analyzed: {report['records_analyzed']} | Window: {report['timeframe_days']} days | Generated: {report['generated_at']}"
    )
    agent_totals = report.get("agent_type_totals", {})
    if agent_totals:
        auto_cost = agent_totals.get(CostAnalytics.AUTO_ALLOW_LABEL, {}).get("cost", 0.0)
        orchestrator_cost = agent_totals.get(CostAnalytics.ORCHESTRATOR_LABEL, {}).get("cost", 0.0)
        other_cost = agent_totals.get(CostAnalytics.OTHER_LABEL, {}).get("cost", 0.0)
        overall_cost = agent_totals.get("overall", {}).get("cost", auto_cost + orchestrator_cost + other_cost)
        print(
            f"Auto-Allow: {format_currency(auto_cost)} | Master Orchestrator: {format_currency(orchestrator_cost)} | Other: {format_currency(other_cost)} | Total: {format_currency(overall_cost)}"
        )

    print_agent_spend(report.get("agent_type_spend", {}))
    print_cost_table("Top panels by cost", report.get("cost_per_panel", []))
    print_cost_table("Top repositories by cost", report.get("cost_per_repo", []))
    print_model_distribution(report.get("model_usage_distribution", []))
    describe_trend(report.get("trend", {}))
    describe_outliers(report.get("outliers", []))
    print_recommendations(report.get("recommendations", []))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    analytics = CostAnalytics(metrics_path=args.metrics_path)
    report = analytics.generate_report(days=args.days, panel_limit=args.panel_limit, repo_limit=args.repo_limit)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print_report(report)


if __name__ == "__main__":
    main()