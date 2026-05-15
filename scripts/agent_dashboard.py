#!/usr/bin/env python3
"""Live dashboard for managed agent panels."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
except ImportError:  # pragma: no cover
    Console = None
    Group = None
    Live = None
    Panel = None
    Table = None

from automation.config import ALLOW_METRICS_LOG_PATH, MAX_ALLOWS_PER_HOUR
from automation.cost_tracker import (
    DEFAULT_COST_METRICS_PATH,
    CostTracker,
    get_cost_tracker,
)
from automation.metrics import get_metrics_tracker
from automation.orchestration_v1.ledger import OrchestrationLedger
from automation.panel_state import (
    PanelState,
    PanelStatus,
    QualityStatus,
    extract_repo_name_from_title,
)
from automation.panel_task_dispatcher import TaskPanelDispatcher
from automation.panel_tracker_core import DEFAULT_PANEL_STATE_PATH
from automation.prompt_resolver import PROMPT_FEED_FILENAME, REPO_PROMPT_MAP

DEFAULT_LEDGER_PATH = PROJECT_ROOT / "state" / "orchestration" / "global_ledger.jsonl"
STATUS_COLORS = {
    "RUNNING": "green",
    "FINISHED": "yellow",
    "IDLE": "grey70",
    "BLOCKED": "red",
}
ANSI_STATUS_COLORS = {
    "RUNNING": "\x1b[32m",
    "FINISHED": "\x1b[33m",
    "IDLE": "\x1b[90m",
    "BLOCKED": "\x1b[31m",
}
ANSI_RESET = "\x1b[0m"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_timestamp(value: str | None) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        return value or "-"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _truncate(text: str | None, limit: int) -> str:
    normalized = (text or "").strip().replace("\n", " ").replace("\r", " ")
    if not normalized:
        return "-"
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _load_panels(state_path: Path) -> list[PanelState]:
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    panels: list[PanelState] = []
    for panel_data in data.get("panels", {}).values():
        if not isinstance(panel_data, dict):
            continue
        try:
            panels.append(PanelState.from_dict(panel_data))
        except Exception:
            continue
    return panels


def _normalize_repo_name(panel: PanelState) -> str:
    repo_name = panel.repo_name or extract_repo_name_from_title(panel.window_title)
    return repo_name or "-"


def _panel_label(panel: PanelState, index: int) -> str:
    panel_id = (panel.panel_id or "").strip()
    digits = "".join(ch for ch in panel_id if ch.isdigit())
    if digits:
        return f"Panel {digits}"
    if panel_id:
        return panel_id
    return f"Panel {index}"


def _panel_status(panel: PanelState) -> str:
    quality = panel.quality_assessment.status if panel.quality_assessment else None
    if panel.status == PanelStatus.ERROR or quality == QualityStatus.BLOCKED:
        return "BLOCKED"
    if panel.status in {PanelStatus.FINISHED, PanelStatus.COMPLETED} or quality == QualityStatus.COMPLETED:
        return "FINISHED"
    if panel.is_running or panel.status in {
        PanelStatus.RUNNING,
        PanelStatus.WAITING_ALLOW,
        PanelStatus.RATE_LIMITED,
        PanelStatus.NEEDS_INPUT,
    }:
        return "RUNNING"
    return "IDLE"


def _task_preview(panel: PanelState) -> str:
    candidate = panel.assigned_task_name or panel.assigned_prompt_text or panel.last_seed_prompt_text
    return _truncate(candidate, 50)


def _repo_filter_matches(repo_name: str, requested_repo: str | None) -> bool:
    if not requested_repo:
        return True
    return repo_name.lower() == requested_repo.lower()


def _load_last_jsonl_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _load_allow_rate(path: Path) -> dict[str, Any]:
    latest = _load_last_jsonl_record(path) or {}
    retention_minutes = int(latest.get("retention_minutes") or 60)
    allows_last_window = float(latest.get("allows_last_window") or 0.0)
    allows_per_hour = allows_last_window * (60.0 / retention_minutes) if retention_minutes > 0 else 0.0
    return {
        "allows_per_hour": round(allows_per_hour, 2),
        "allows_last_window": allows_last_window,
        "retention_minutes": retention_minutes,
        "last_allow_time": latest.get("last_allow_time"),
        "max_allows_per_hour": int(latest.get("max_allows_per_hour") or MAX_ALLOWS_PER_HOUR),
    }


def _load_total_cost(cost_path: Path) -> float:
    tracker = CostTracker(metrics_path=cost_path)
    report = tracker.get_cost_report(days=3650)
    if not isinstance(report, dict) or report.get("error"):
        return 0.0
    return float(report.get("total_cost") or 0.0)


def _load_session_cost() -> float:
    totals = get_cost_tracker().get_session_totals()
    session_cost = float(totals.get("total_cost") or 0.0)
    if session_cost > 0:
        return session_cost
    summary = get_metrics_tracker().get_summary()
    return float(summary.get("latest_total_cost") or 0.0)


def _discover_repo_names(panels: Iterable[PanelState], dispatcher: TaskPanelDispatcher) -> list[str]:
    repo_names = {
        repo_name
        for repo_name in (_normalize_repo_name(panel) for panel in panels)
        if repo_name and repo_name != "-"
    }
    repo_names.update(REPO_PROMPT_MAP.keys())

    feed_root = dispatcher.feed_root
    if feed_root.exists():
        for child in feed_root.iterdir():
            if child.is_dir() and (child / PROMPT_FEED_FILENAME).exists():
                repo_names.add(child.name)

    return sorted(repo_names, key=str.lower)


def _load_queue_depths(repo_names: Iterable[str], dispatcher: TaskPanelDispatcher) -> dict[str, int]:
    queue_depths: dict[str, int] = {}
    for repo_name in repo_names:
        path = dispatcher._resolve_prompt_path_for_repo(repo_name)
        if not path.exists():
            queue_depths[repo_name] = 0
            continue
        cache = dispatcher._get_feed_cache(repo_name)
        queue_depths[repo_name] = len(cache.entries)
    return queue_depths


def _ledger_outcome(row: dict[str, Any]) -> str:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    decision = payload.get("decision") if isinstance(payload, dict) else None
    if isinstance(decision, dict) and decision.get("action"):
        return str(decision["action"]).upper()

    event = str(row.get("event") or "")
    event_map = {
        "run_completed": "COMPLETED",
        "run_failed": "FAILED",
        "run_blocked": "BLOCKED",
        "run_stopped": "STOPPED",
    }
    if event in event_map:
        return event_map[event]
    return event.replace("run_", "").replace("_", " ").upper() or "UNKNOWN"


def _load_last_orchestration(ledger_path: Path) -> dict[str, Any] | None:
    rows = OrchestrationLedger(ledger_path).read_rows()
    if not rows:
        return None
    latest = rows[-1]
    return {
        "timestamp": latest.get("ts"),
        "event": latest.get("event"),
        "outcome": _ledger_outcome(latest),
    }


def build_dashboard_snapshot(
    *,
    state_path: Path = DEFAULT_PANEL_STATE_PATH,
    allow_metrics_path: Path = ALLOW_METRICS_LOG_PATH,
    cost_path: Path = DEFAULT_COST_METRICS_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    repo: str | None = None,
) -> dict[str, Any]:
    panels = _load_panels(state_path)
    filtered_panels = []
    for index, panel in enumerate(sorted(panels, key=lambda item: (_normalize_repo_name(item).lower(), item.window_title.lower())), start=1):
        repo_name = _normalize_repo_name(panel)
        if not _repo_filter_matches(repo_name, repo):
            continue
        filtered_panels.append(
            {
                "panel": _panel_label(panel, index),
                "panel_id": panel.panel_id,
                "repo": repo_name,
                "status": _panel_status(panel),
                "task_preview": _task_preview(panel),
                "window_title": panel.window_title,
                "is_running": panel.is_running,
                "last_scanned": panel.last_scanned.isoformat() if panel.last_scanned else None,
            }
        )

    queue_dispatcher = TaskPanelDispatcher(allow_default_fallback=False)
    repo_names = _discover_repo_names(panels, queue_dispatcher)
    if repo:
        repo_names = [name for name in repo_names if _repo_filter_matches(name, repo)]
        if repo and repo not in repo_names:
            repo_names.append(repo)
    queue_depths = _load_queue_depths(repo_names, queue_dispatcher)

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "repo_filter": repo,
        "panels": filtered_panels,
        "queue_depths": queue_depths,
        "session_cost": round(_load_session_cost(), 4),
        "total_cost": round(_load_total_cost(cost_path), 4),
        "allow_rate": _load_allow_rate(allow_metrics_path),
        "last_orchestration": _load_last_orchestration(ledger_path),
    }


def _format_status_plain(status: str) -> str:
    color = ANSI_STATUS_COLORS.get(status, "")
    return f"{color}{status}{ANSI_RESET}" if color else status


def _queue_summary(queue_depths: dict[str, int]) -> str:
    if not queue_depths:
        return "-"
    return "  ".join(f"{name}:{depth}" for name, depth in sorted(queue_depths.items(), key=lambda item: item[0].lower()))


def _last_orchestration_summary(snapshot: dict[str, Any]) -> str:
    last_event = snapshot.get("last_orchestration") or {}
    if not last_event:
        return "LAST ORCHESTRATION  None"
    return (
        "LAST ORCHESTRATION  "
        f"{last_event.get('outcome', 'UNKNOWN')}  {_format_timestamp(last_event.get('timestamp'))}"
    )


def render_plain(snapshot: dict[str, Any]) -> str:
    lines = [
        f"AGENT ESTATE DASHBOARD  --  {_format_timestamp(snapshot.get('generated_at'))}",
        f"{'Panel':<10} | {'Repo':<12} | {'Status':<10} | Task (preview 50 chars)",
    ]
    panels = snapshot.get("panels") or []
    if panels:
        for row in panels:
            lines.append(
                f"{row['panel']:<10} | {row['repo']:<12} | {_format_status_plain(row['status']):<19} | {row['task_preview']}"
            )
    else:
        lines.append("- No managed panels found")

    allow_rate = snapshot.get("allow_rate") or {}
    lines.append(f"QUEUE  {_queue_summary(snapshot.get('queue_depths') or {})}")
    lines.append(
        "COST   "
        f"Session: ${snapshot.get('session_cost', 0.0):.2f}   Total: ${snapshot.get('total_cost', 0.0):.2f}"
    )
    lines.append(
        "RATE   "
        f"Allows/hr: {allow_rate.get('allows_per_hour', 0):.0f}"
        f"/{allow_rate.get('max_allows_per_hour', MAX_ALLOWS_PER_HOUR)}"
    )
    lines.append(_last_orchestration_summary(snapshot))
    return "\n".join(lines)


def _build_rich_renderable(snapshot: dict[str, Any]):
    header = f"[bold]AGENT ESTATE DASHBOARD[/bold]  --  {_format_timestamp(snapshot.get('generated_at'))}"

    table = Table(expand=True)
    table.add_column("Panel", no_wrap=True)
    table.add_column("Repo", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Task (preview 50 chars)")
    panels = snapshot.get("panels") or []
    if panels:
        for row in panels:
            color = STATUS_COLORS.get(row["status"], "white")
            table.add_row(
                row["panel"],
                row["repo"],
                f"[{color}]{row['status']}[/{color}]",
                row["task_preview"],
            )
    else:
        table.add_row("-", "-", "[grey70]IDLE[/grey70]", "No managed panels found")

    queue_line = f"[bold]QUEUE[/bold]  {_queue_summary(snapshot.get('queue_depths') or {})}"
    cost_line = (
        "[bold]COST[/bold]   "
        f"Session: ${snapshot.get('session_cost', 0.0):.2f}   Total: ${snapshot.get('total_cost', 0.0):.2f}"
    )
    allow_rate = snapshot.get("allow_rate") or {}
    rate_line = (
        "[bold]RATE[/bold]   "
        f"Allows/hr: {allow_rate.get('allows_per_hour', 0):.0f}"
        f"/{allow_rate.get('max_allows_per_hour', MAX_ALLOWS_PER_HOUR)}"
    )
    footer = _last_orchestration_summary(snapshot)
    return Panel(Group(header, table, queue_line, cost_line, rate_line, footer), border_style="blue")


def _emit_snapshot(snapshot: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(snapshot, indent=2))
        return

    if Console is not None and Group is not None and Panel is not None:
        Console().print(_build_rich_renderable(snapshot))
        return

    print(render_plain(snapshot))


def _watch(args: argparse.Namespace) -> int:
    if args.json:
        raise SystemExit("--watch cannot be combined with --json")

    console = Console() if Console is not None else None
    live = Live(console=console, refresh_per_second=4) if console is not None and Live is not None else None

    try:
        if live is not None:
            with live:
                while True:
                    snapshot = build_dashboard_snapshot(
                        state_path=args.state_path,
                        allow_metrics_path=args.allow_metrics_path,
                        cost_path=args.cost_path,
                        ledger_path=args.ledger_path,
                        repo=args.repo,
                    )
                    live.update(_build_rich_renderable(snapshot), refresh=True)
                    time.sleep(args.interval)
        else:
            while True:
                snapshot = build_dashboard_snapshot(
                    state_path=args.state_path,
                    allow_metrics_path=args.allow_metrics_path,
                    cost_path=args.cost_path,
                    ledger_path=args.ledger_path,
                    repo=args.repo,
                )
                os.system("cls" if os.name == "nt" else "clear")
                print(render_plain(snapshot))
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a live dashboard for managed agent panels")
    parser.add_argument("--watch", action="store_true", help="Refresh continuously")
    parser.add_argument("--interval", type=float, default=5.0, help="Refresh interval in seconds for --watch")
    parser.add_argument("--json", action="store_true", help="Emit dashboard data as JSON")
    parser.add_argument("--repo", help="Filter dashboard data to a single repo")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_PANEL_STATE_PATH,
        help="Path to panel_state.json",
    )
    parser.add_argument(
        "--allow-metrics-path",
        type=Path,
        default=ALLOW_METRICS_LOG_PATH,
        help="Path to allow_metrics.jsonl",
    )
    parser.add_argument(
        "--cost-path",
        type=Path,
        default=DEFAULT_COST_METRICS_PATH,
        help="Path to cost_metrics.jsonl",
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Path to the orchestration_v1 ledger JSONL file",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.watch:
        return _watch(args)

    snapshot = build_dashboard_snapshot(
        state_path=args.state_path,
        allow_metrics_path=args.allow_metrics_path,
        cost_path=args.cost_path,
        ledger_path=args.ledger_path,
        repo=args.repo,
    )
    _emit_snapshot(snapshot, json_mode=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())