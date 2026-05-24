#!/usr/bin/env python3
"""Unified telemetry aggregation, dashboards, and report generation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation.paths import allow_metrics_log_path, load_automation_env, panel_state_path

load_automation_env()

try:  # Optional rich dependency for dashboards
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
except ImportError:  # pragma: no cover
    Console = None
    Layout = None
    Live = None
    Panel = None
    Table = None


DEFAULT_HISTORY_PATH = PROJECT_ROOT / "logs" / "metrics_reports" / "history.jsonl"
DEFAULT_EXPORT_PATH = PROJECT_ROOT / "logs" / "metrics_reports" / "latest_summary.json"
DEFAULT_MARKDOWN_EXPORT_PATH = PROJECT_ROOT / "logs" / "metrics_reports" / "latest_summary.md"


@dataclass(frozen=True)
class TelemetryPaths:
    metrics_json: Path = PROJECT_ROOT / "automation" / "metrics.json"
    metrics_jsonl: Path = PROJECT_ROOT / "automation" / "metrics.jsonl"
    assignment_metrics: Path = PROJECT_ROOT / "automation" / "assignment_metrics.jsonl"
    allow_metrics: Path = allow_metrics_log_path()
    panel_state: Path = panel_state_path()
    cost_metrics: Path = PROJECT_ROOT / "logs" / "cost_metrics.jsonl"


@dataclass
class RawTelemetry:
    prompt_metrics: List[dict]
    model_metrics: List[dict]
    response_metrics: List[dict]
    cost_metrics: List[dict]
    assignment_metrics: List[dict]
    allow_metrics: List[dict]
    panel_state: dict
    workflow_metrics: List[dict]
    metrics_log_events: List[dict]


class FileLoader:
    """Load JSON and JSONL files safely."""

    @staticmethod
    def load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def load_jsonl(path: Path) -> List[dict]:
        if not path.exists():
            return []
        payload: List[dict] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        return payload


class RetentionManager:
    """Maintains rolling metric history for baselines and anomaly detection."""

    def __init__(self, history_path: Path, retention_days: int) -> None:
        self.history_path = history_path
        self.retention_days = retention_days
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_history(self) -> List[dict]:
        if not self.history_path.exists():
            return []
        records: List[dict] = []
        with self.history_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        return records

    def _prune(self, records: List[dict]) -> List[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept: List[dict] = []
        for entry in records:
            ts_raw = entry.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts_val = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
            if ts_val >= cutoff:
                kept.append(entry)
        return kept

    def append_snapshot(self, snapshot: dict) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success_rate": snapshot.get("panel_seeding", {}).get("overall_success_rate", 0.0),
            "error_rate": snapshot.get("errors", {}).get("overall_error_rate", 0.0),
            "cost_per_completion": snapshot.get("cost", {}).get("cost_per_completion", 0.0),
            "tasks_per_hour": snapshot.get("productivity", {}).get("tasks_per_hour", 0.0),
        }
        records = self._load_history()
        records.append(payload)
        records = self._prune(records)
        with self.history_path.open("w", encoding="utf-8") as handle:
            for entry in records:
                handle.write(json.dumps(entry) + "\n")

    def load_baseline(self, days: int) -> dict:
        records = self._load_history()
        if not records:
            return {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = []
        for entry in records:
            ts_raw = entry.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts_val = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
            if ts_val >= cutoff:
                filtered.append(entry)
        if not filtered:
            filtered = records
        aggregates: Dict[str, float] = {}
        for key in ("success_rate", "error_rate", "cost_per_completion", "tasks_per_hour"):
            values = [entry.get(key, 0.0) for entry in filtered]
            if values:
                aggregates[key] = float(mean(values))
        return aggregates


class ReportWriter:
    """Writes exports and periodic summaries to disk."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.daily_dir = base_dir / "daily"
        self.weekly_dir = base_dir / "weekly"
        self.monthly_dir = base_dir / "monthly"
        for directory in (self.base_dir, self.daily_dir, self.weekly_dir, self.monthly_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def write_snapshot_exports(self, snapshot: dict, json_path: Path, markdown_path: Path) -> None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        with markdown_path.open("w", encoding="utf-8") as handle:
            handle.write(self._build_markdown(snapshot))

    def write_periodic_reports(self, snapshot: dict) -> None:
        now = datetime.now(timezone.utc)
        self._write_period("daily", 1, now, snapshot, self.daily_dir)
        self._write_period("weekly", 7, now, snapshot, self.weekly_dir)
        self._write_period("monthly", 30, now, snapshot, self.monthly_dir)

    def _write_period(self, label: str, days: int, timestamp: datetime, snapshot: dict, target: Path) -> None:
        payload = {
            "generated_at": timestamp.isoformat(),
            "label": label,
            "days_included": days,
            "success_rate": snapshot.get("panel_seeding", {}).get("overall_success_rate", 0.0),
            "cost_per_completion": snapshot.get("cost", {}).get("cost_per_completion", 0.0),
            "tasks_per_hour": snapshot.get("productivity", {}).get("tasks_per_hour", 0.0),
            "top_repos": snapshot.get("repo_heatmap", {}).get("hotspots", [])[:5],
            "model_mix": snapshot.get("model_distribution", {}).get("models", [])[:5],
            "alerts": snapshot.get("alerts", []),
        }
        target.mkdir(parents=True, exist_ok=True)
        stub = timestamp.strftime("%Y-%m-%d_%H%M%S")
        json_path = target / f"{stub}.json"
        md_path = target / f"{stub}.md"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        with md_path.open("w", encoding="utf-8") as handle:
            handle.write(self._build_markdown(payload))

    def _build_markdown(self, snapshot: dict) -> str:
        success_rate = snapshot.get("panel_seeding", {}).get("overall_success_rate")
        if success_rate is None:
            success_rate = snapshot.get("success_rate", 0.0)
        tasks_per_hour = snapshot.get("productivity", {}).get("tasks_per_hour")
        if tasks_per_hour is None:
            tasks_per_hour = snapshot.get("tasks_per_hour", 0.0)
        cost_per_completion = snapshot.get("cost", {}).get("cost_per_completion")
        if cost_per_completion is None:
            cost_per_completion = snapshot.get("cost_per_completion", 0.0)
        error_rate = snapshot.get("errors", {}).get("overall_error_rate")
        if error_rate is None:
            error_rate = snapshot.get("error_rate", 0.0)
        lines = [
            f"# Metrics Summary ({snapshot.get('generated_at', datetime.now(timezone.utc).isoformat())})",
            "",
            "## Key Performance",
            f"- Overall success rate: {success_rate:.1%}",
            f"- Tasks per hour: {tasks_per_hour:.2f}",
            f"- Cost per completion: ${cost_per_completion:.4f}",
            f"- Error rate: {error_rate:.1%}",
            "",
            "## Model Distribution",
        ]
        model_entries = snapshot.get("model_distribution", {}).get("models")
        if not model_entries:
            model_entries = snapshot.get("model_mix", [])
        for record in model_entries[:5]:
            lines.append(
                f"- {record['model']}: {record['count']} calls, {record['success_rate']:.1%} success"
            )
        lines.append("")
        hotspots = snapshot.get("repo_heatmap", {}).get("hotspots")
        if not hotspots:
            hotspots = snapshot.get("top_repos", [])
        lines.append("## Repo Hotspots")
        for hotspot in hotspots[:5]:
            lines.append(
                f"- {hotspot['repo']} at hour {hotspot['hour']:02d}: {hotspot['count']} assignments"
            )
        lines.append("")
        alerts = snapshot.get("alerts") or snapshot.get("alert_list") or []
        if alerts:
            lines.append("## Alerts")
            for alert in alerts:
                lines.append(f"- {alert}")
        else:
            lines.append("## Alerts\n- No active alerts")
        lines.append("")
        return "\n".join(lines)


class TelemetryAggregator:
    """Loads telemetry sources and produces derived analytics."""

    def __init__(
        self,
        paths: TelemetryPaths,
        *,
        retention_days: int,
        baseline_days: int,
        history_path: Path,
    ) -> None:
        self.paths = paths
        self.retention = RetentionManager(history_path, retention_days)
        self.baseline_days = baseline_days
        self.report_writer = ReportWriter(history_path.parent)

    def load_raw(self) -> RawTelemetry:
        metrics_blob = FileLoader.load_json(self.paths.metrics_json)
        prompt_metrics = list(metrics_blob.get("prompt_metrics", []))
        model_metrics = list(metrics_blob.get("model_metrics", []))
        response_metrics = list(metrics_blob.get("response_feedback_metrics", []))
        cost_metrics = list(metrics_blob.get("cost_metrics", []))
        workflow_metrics = list(metrics_blob.get("workflow_metrics", []))
        metrics_jsonl = FileLoader.load_jsonl(self.paths.metrics_jsonl)
        assignments = FileLoader.load_jsonl(self.paths.assignment_metrics)
        allow_metrics = FileLoader.load_jsonl(self.paths.allow_metrics)
        cost_log = FileLoader.load_jsonl(self.paths.cost_metrics)
        if cost_log:
            cost_metrics.extend(cost_log)
        panel_state = FileLoader.load_json(self.paths.panel_state)
        if metrics_jsonl:
            for entry in metrics_jsonl:
                if "prompt_index" in entry:
                    prompt_metrics.append(entry)
                elif "model_label" in entry:
                    model_metrics.append(entry)
                elif entry.get("response_category"):
                    response_metrics.append(entry)
        return RawTelemetry(
            prompt_metrics=prompt_metrics,
            model_metrics=model_metrics,
            response_metrics=response_metrics,
            cost_metrics=cost_metrics,
            assignment_metrics=assignments,
            allow_metrics=allow_metrics,
            panel_state=panel_state,
            workflow_metrics=workflow_metrics,
            metrics_log_events=metrics_jsonl,
        )

    def build_snapshot(self, *, persist: bool = True) -> dict:
        raw = self.load_raw()
        panel_seeding = self._panel_seeding_metrics(raw.prompt_metrics)
        model_mix = self._model_distribution(raw.prompt_metrics, raw.model_metrics)
        repo_heatmap = self._repo_heatmap(raw.assignment_metrics)
        productivity = self._productivity_metrics(raw.response_metrics, raw.panel_state)
        errors = self._error_trends(raw.response_metrics)
        cost = self._cost_metrics(raw.cost_metrics, productivity["completed_tasks"])
        desktop_switching = self._desktop_switching(raw.allow_metrics)
        panel_state_summary = self._panel_state_summary(raw.panel_state)
        alerts = self._detect_alerts(panel_seeding, errors, cost, productivity)
        snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "panel_seeding": panel_seeding,
            "model_distribution": model_mix,
            "repo_heatmap": repo_heatmap,
            "productivity": productivity,
            "errors": errors,
            "cost": cost,
            "desktop_switching": desktop_switching,
            "panel_state": panel_state_summary,
            "alerts": alerts,
        }
        if persist:
            self.retention.append_snapshot(snapshot)
            self.report_writer.write_periodic_reports(snapshot)
        return snapshot

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _panel_seeding_metrics(self, prompt_metrics: List[dict]) -> dict:
        totals = {"success": 0, "failure": 0}
        buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"success": 0, "total": 0})
        for metric in prompt_metrics:
            ts = self._parse_timestamp(metric.get("timestamp"))
            key = ts.date().isoformat() if ts else "unknown"
            is_success = bool(metric.get("success"))
            buckets[key]["total"] += 1
            if is_success:
                buckets[key]["success"] += 1
                totals["success"] += 1
            else:
                totals["failure"] += 1
        total_prompts = totals["success"] + totals["failure"]
        trend = []
        for day, data in sorted(buckets.items()):
            rate = data["success"] / data["total"] if data["total"] else 0.0
            trend.append({"day": day, "success_rate": rate, "success": data["success"], "total": data["total"]})
        slope = self._calculate_slope([point["success_rate"] for point in trend])
        overall_rate = totals["success"] / total_prompts if total_prompts else 0.0
        chart = self._ascii_sparkline([point["success_rate"] for point in trend])
        return {
            "total_prompts": total_prompts,
            "successes": totals["success"],
            "failures": totals["failure"],
            "overall_success_rate": overall_rate,
            "trend": trend,
            "trend_slope": slope,
            "trend_chart": chart,
        }

    def _model_distribution(self, prompt_metrics: List[dict], model_metrics: List[dict]) -> dict:
        counts = Counter()
        for metric in prompt_metrics:
            model = metric.get("model_requested") or "unknown"
            counts[model] += 1
        effectiveness: Dict[str, Dict[str, int]] = defaultdict(lambda: {"success": 0, "total": 0})
        for metric in model_metrics:
            label = metric.get("model_label") or metric.get("model_requested") or "unknown"
            effectiveness[label]["total"] += 1
            if metric.get("success"):
                effectiveness[label]["success"] += 1
        models = []
        for model, total in sorted(counts.items(), key=lambda item: item[1], reverse=True):
            eff = effectiveness.get(model, {"success": 0, "total": 0})
            success_rate = eff["success"] / eff["total"] if eff["total"] else 0.0
            models.append({"model": model, "count": total, "success_rate": success_rate})
        fairness = self._round_robin_fairness(prompt_metrics)
        return {"models": models, "round_robin": fairness}

    def _round_robin_fairness(self, prompt_metrics: List[dict]) -> dict:
        index_counts = Counter()
        for metric in prompt_metrics:
            index_counts[int(metric.get("prompt_index", -1))] += 1
        if not index_counts:
            return {"distribution": {}, "fairness_score": 1.0}
        values = list(index_counts.values())
        avg = mean(values)
        spread = pstdev(values) if len(values) > 1 else 0.0
        fairness_score = 1.0 if avg == 0 else max(0.0, 1.0 - (spread / (avg + 1e-6)))
        most = max(index_counts, key=index_counts.get)
        least = min(index_counts, key=index_counts.get)
        return {
            "distribution": dict(sorted(index_counts.items())),
            "fairness_score": fairness_score,
            "balance_tip": {
                "heaviest_index": most,
                "lightest_index": least,
                "difference": index_counts[most] - index_counts[least],
            },
        }

    def _repo_heatmap(self, assignments: List[dict]) -> dict:
        bucket: Dict[str, List[int]] = defaultdict(lambda: [0] * 24)
        for entry in assignments:
            repo = entry.get("repo") or "unknown"
            ts = self._parse_timestamp(entry.get("timestamp"))
            hour = ts.hour if ts else 0
            bucket[repo][hour] += 1
        hotspots = []
        for repo, hours in bucket.items():
            peak_hour = max(range(24), key=lambda idx: hours[idx])
            hotspots.append({"repo": repo, "hour": peak_hour, "count": hours[peak_hour]})
        hotspots.sort(key=lambda item: item["count"], reverse=True)
        matrix = {repo: hours for repo, hours in bucket.items()}
        return {"matrix": matrix, "hotspots": hotspots}

    def _productivity_metrics(self, response_metrics: List[dict], panel_state: dict) -> dict:
        completed = [metric for metric in response_metrics if metric.get("response_category") == "completed"]
        completed_count = len(completed)
        per_hour: Dict[str, int] = defaultdict(int)
        durations: List[float] = []
        for metric in completed:
            ts = self._parse_timestamp(metric.get("timestamp"))
            hour_key = ts.replace(minute=0, second=0, microsecond=0).isoformat() if ts else "unknown"
            per_hour[hour_key] += 1
            if metric.get("processing_time_seconds") is not None:
                durations.append(float(metric.get("processing_time_seconds")))
        avg_duration = mean(durations) if durations else 0.0
        sorted_hours = sorted(per_hour.items())
        chart = self._ascii_bar_chart([count for _, count in sorted_hours])
        active_panels = len(panel_state.get("panels", {})) if isinstance(panel_state.get("panels"), dict) else 0
        total_hours = max(1, len(per_hour) or 1)
        tasks_per_hour = completed_count / total_hours
        return {
            "completed_tasks": completed_count,
            "tasks_per_hour": tasks_per_hour,
            "average_duration_seconds": avg_duration,
            "per_hour": sorted_hours,
            "per_hour_chart": chart,
            "active_panels": active_panels,
        }

    def _error_trends(self, response_metrics: List[dict]) -> dict:
        by_category: Dict[str, int] = defaultdict(int)
        by_day: Dict[str, Dict[str, int]] = defaultdict(lambda: {"error": 0, "total": 0})
        for metric in response_metrics:
            category = metric.get("response_category") or "unknown"
            by_category[category] += 1
            ts = self._parse_timestamp(metric.get("timestamp"))
            day = ts.date().isoformat() if ts else "unknown"
            by_day[day]["total"] += 1
            if category == "error":
                by_day[day]["error"] += 1
        trend = []
        for day, payload in sorted(by_day.items()):
            rate = payload["error"] / payload["total"] if payload["total"] else 0.0
            trend.append({"day": day, "error_rate": rate, "errors": payload["error"], "total": payload["total"]})
        overall_error_rate = 0.0
        total_events = sum(item["total"] for item in by_day.values())
        if total_events:
            overall_error_rate = sum(item["error"] for item in by_day.values()) / total_events
        chart = self._ascii_sparkline([point["error_rate"] for point in trend])
        return {
            "by_category": dict(sorted(by_category.items(), key=lambda item: item[1], reverse=True)),
            "trend": trend,
            "overall_error_rate": overall_error_rate,
            "trend_chart": chart,
        }

    def _cost_metrics(self, cost_metrics: List[dict], completed_tasks: int) -> dict:
        daily_totals: Dict[str, float] = defaultdict(float)
        total_cost = 0.0
        for record in cost_metrics:
            ts = self._parse_timestamp(record.get("timestamp"))
            day = ts.date().isoformat() if ts else "unknown"
            value = float(record.get("total_cost", 0.0))
            daily_totals[day] += value
            total_cost += value
        sorted_days = sorted(daily_totals.items())
        chart = self._ascii_bar_chart([total for _, total in sorted_days])
        cost_per_completion = total_cost / completed_tasks if completed_tasks else total_cost
        spike_alerts = []
        if sorted_days:
            baseline = mean(value for _, value in sorted_days[:-1]) if len(sorted_days) > 1 else sorted_days[0][1]
            latest = sorted_days[-1][1]
            if baseline and latest >= baseline * 1.5:
                spike_alerts.append(
                    f"Latest daily cost ${latest:.2f} exceeds 150% of baseline ${baseline:.2f}"
                )
        return {
            "total_cost": total_cost,
            "daily_totals": sorted_days,
            "cost_per_completion": cost_per_completion,
            "trend_chart": chart,
            "cost_alerts": spike_alerts,
        }

    def _desktop_switching(self, allow_metrics: List[dict]) -> dict:
        if not allow_metrics:
            return {
                "average_allows": 0.0,
                "average_panels": 0.0,
                "reliability_score": 1.0,
                "switch_failures": 0,
            }
        allow_rates: List[float] = []
        failures = 0
        total_allows: List[float] = []
        total_panels: List[float] = []
        for record in allow_metrics:
            allows = float(record.get("allows_last_window", 0.0))
            panels = float(record.get("panels_last_window", 0.0))
            total_allows.append(allows)
            total_panels.append(panels)
            if panels > 0:
                allow_rates.append(allows / panels)
            else:
                failures += 1
        reliability = mean(allow_rates) if allow_rates else 0.0
        return {
            "average_allows": mean(total_allows) if total_allows else 0.0,
            "average_panels": mean(total_panels) if total_panels else 0.0,
            "reliability_score": reliability,
            "switch_failures": failures,
        }

    def _panel_state_summary(self, panel_state: dict) -> dict:
        panels = panel_state.get("panels") if isinstance(panel_state, dict) else {}
        if not isinstance(panels, dict):
            return {"status_counts": {}, "running_panels": 0}
        status_counts: Dict[str, int] = defaultdict(int)
        repo_counts: Dict[str, int] = defaultdict(int)
        for data in panels.values():
            status = str(data.get("status", "unknown"))
            status_counts[status] += 1
            repo = data.get("repo_name") or "unknown"
            repo_counts[repo] += 1
        running = status_counts.get("running", 0)
        return {
            "status_counts": dict(status_counts),
            "repo_counts": dict(sorted(repo_counts.items(), key=lambda item: item[1], reverse=True)),
            "running_panels": running,
        }

    def _detect_alerts(self, panel_seeding: dict, errors: dict, cost: dict, productivity: dict) -> List[str]:
        alerts: List[str] = []
        baseline = self.retention.load_baseline(self.baseline_days)
        success_rate = panel_seeding.get("overall_success_rate", 0.0)
        baseline_success = baseline.get("success_rate")
        if baseline_success is not None and success_rate < baseline_success * 0.8:
            alerts.append(
                f"Success rate dropped below baseline ({success_rate:.1%} vs {baseline_success:.1%})."
            )
        error_rate = errors.get("overall_error_rate", 0.0)
        baseline_error = baseline.get("error_rate")
        if baseline_error is not None and error_rate > baseline_error * 1.25:
            alerts.append(
                f"Error rate exceeds baseline ({error_rate:.1%} vs {baseline_error:.1%})."
            )
        cost_per_completion = cost.get("cost_per_completion", 0.0)
        baseline_cost = baseline.get("cost_per_completion")
        if baseline_cost is not None and cost_per_completion > baseline_cost * 1.4:
            alerts.append(
                f"Cost per completion climbed ({cost_per_completion:.4f} vs {baseline_cost:.4f})."
            )
        tasks_per_hour = productivity.get("tasks_per_hour", 0.0)
        baseline_tph = baseline.get("tasks_per_hour")
        if baseline_tph is not None and tasks_per_hour < baseline_tph * 0.7:
            alerts.append(
                f"Productivity dip detected ({tasks_per_hour:.2f} vs {baseline_tph:.2f} tasks/hour)."
            )
        alerts.extend(cost.get("cost_alerts", []))
        return alerts

    @staticmethod
    def _calculate_slope(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        return (values[-1] - values[0]) / (len(values) - 1)

    @staticmethod
    def _ascii_sparkline(values: Iterable[float], width: int = 40) -> str:
        series = list(values)
        if not series:
            return ""
        max_value = max(series)
        if max_value == 0:
            return "".ljust(min(len(series), width), "-")
        normalized = [int((value / max_value) * width) for value in series]
        parts = ["#" * max(1, val) for val in normalized]
        return " ".join(parts)

    @staticmethod
    def _ascii_bar_chart(values: Iterable[float], width: int = 30) -> str:
        items = list(values)
        if not items:
            return ""
        max_value = max(items)
        lines = []
        for value in items:
            filled = int((value / max_value) * width) if max_value else 0
            lines.append(f"[{value:.1f}] " + ("#" * filled))
        return "\n".join(lines)


class DashboardRenderer:
    """Renders live dashboards via rich."""

    def __init__(self) -> None:
        if Console is None or Layout is None or Live is None or Panel is None or Table is None:
            raise RuntimeError("rich is required for dashboard mode. Install it via `pip install rich`.")
        self.console = Console()

    def render(self, snapshot: dict) -> Layout:
        layout = Layout()
        layout.split_column(Layout(name="top", size=18), Layout(name="bottom"))
        layout["top"].split_row(
            Layout(self._seeding_panel(snapshot), name="seeding"),
            Layout(self._model_panel(snapshot), name="models"),
            Layout(self._alerts_panel(snapshot), name="alerts"),
        )
        layout["bottom"].split_row(
            Layout(self._productivity_panel(snapshot), name="productivity"),
            Layout(self._cost_panel(snapshot), name="cost"),
            Layout(self._desktop_panel(snapshot), name="desktop"),
        )
        return layout

    def _seeding_panel(self, snapshot: dict) -> Panel:
        table = Table(show_header=True, title="Panel Seeding Trend")
        table.add_column("Day", style="bold")
        table.add_column("Success Rate")
        table.add_column("Chart")
        for entry in snapshot.get("panel_seeding", {}).get("trend", [])[-5:]:
            table.add_row(entry["day"], f"{entry['success_rate']:.1%}", "#" * max(1, int(entry["success_rate"] * 20)))
        summary = f"Overall: {snapshot.get('panel_seeding', {}).get('overall_success_rate', 0.0):.1%}"
        return Panel.fit(table, subtitle=summary)

    def _model_panel(self, snapshot: dict) -> Panel:
        table = Table(show_header=True, title="Model Mix")
        table.add_column("Model", style="bold")
        table.add_column("Calls")
        table.add_column("Success")
        for record in snapshot.get("model_distribution", {}).get("models", [])[:5]:
            table.add_row(record["model"], str(record["count"]), f"{record['success_rate']:.1%}")
        fairness = snapshot.get("model_distribution", {}).get("round_robin", {}).get("fairness_score", 1.0)
        return Panel.fit(table, subtitle=f"Fairness {fairness:.2f}")

    def _alerts_panel(self, snapshot: dict) -> Panel:
        lines = snapshot.get("alerts", []) or ["No active alerts"]
        return Panel("\n".join(f"- {line}" for line in lines), title="Alerts")

    def _productivity_panel(self, snapshot: dict) -> Panel:
        table = Table(show_header=True, title="Productivity")
        table.add_column("Hour", style="bold")
        table.add_column("Tasks")
        for hour, count in snapshot.get("productivity", {}).get("per_hour", [])[-6:]:
            table.add_row(hour[-8:], str(count))
        summary = (
            f"Completed {snapshot.get('productivity', {}).get('completed_tasks', 0)} | "
            f"Avg {snapshot.get('productivity', {}).get('tasks_per_hour', 0.0):.2f}/hr"
        )
        return Panel.fit(table, subtitle=summary)

    def _cost_panel(self, snapshot: dict) -> Panel:
        table = Table(show_header=True, title="Cost Trend")
        table.add_column("Day", style="bold")
        table.add_column("Total")
        for day, total in snapshot.get("cost", {}).get("daily_totals", [])[-5:]:
            table.add_row(day[-5:], f"${total:.2f}")
        subtitle = f"Cost/task ${snapshot.get('cost', {}).get('cost_per_completion', 0.0):.4f}"
        return Panel.fit(table, subtitle=subtitle)

    def _desktop_panel(self, snapshot: dict) -> Panel:
        data = snapshot.get("desktop_switching", {})
        lines = [
            f"Avg allows: {data.get('average_allows', 0.0):.2f}",
            f"Avg panels: {data.get('average_panels', 0.0):.2f}",
            f"Reliability: {data.get('reliability_score', 0.0):.2f}",
            f"Failures: {data.get('switch_failures', 0)}",
        ]
        return Panel("\n".join(lines), title="Desktop Switching")

    def run_live(self, aggregator: TelemetryAggregator, refresh_seconds: float) -> None:
        with Live(refresh_per_second=1, console=self.console) as live:
            while True:
                snapshot = aggregator.build_snapshot(persist=False)
                live.update(self.render(snapshot))
                time.sleep(refresh_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified telemetry and analytics platform")
    parser.add_argument(
        "--mode",
        choices=["dashboard", "export"],
        default="export",
        help="dashboard launches live UI, export writes JSON/Markdown",
    )
    parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=5.0,
        help="Refresh cadence for dashboard mode",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="Number of days to retain snapshot history",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=14,
        help="Days of history used to compute alert baselines",
    )
    parser.add_argument(
        "--history-path",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Location for the rolling history JSONL file",
    )
    parser.add_argument(
        "--export-json",
        type=Path,
        default=DEFAULT_EXPORT_PATH,
        help="Destination for the consolidated JSON export",
    )
    parser.add_argument(
        "--export-markdown",
        type=Path,
        default=DEFAULT_MARKDOWN_EXPORT_PATH,
        help="Destination for the Markdown export",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    aggregator = TelemetryAggregator(
        TelemetryPaths(),
        retention_days=args.retention_days,
        baseline_days=args.baseline_days,
        history_path=args.history_path,
    )
    if args.mode == "dashboard":
        if Console is None:
            raise SystemExit("rich is required for dashboard mode. Install it via `pip install rich`.")
        renderer = DashboardRenderer()
        renderer.run_live(aggregator, args.refresh_seconds)
        return 0
    snapshot = aggregator.build_snapshot()
    aggregator.report_writer.write_snapshot_exports(snapshot, args.export_json, args.export_markdown)
    print(f"Wrote JSON export to {args.export_json}")
    print(f"Wrote Markdown export to {args.export_markdown}")
    if snapshot.get("alerts"):
        print("Active alerts:")
        for alert in snapshot["alerts"]:
            print(f" - {alert}")
    else:
        print("No active alerts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
