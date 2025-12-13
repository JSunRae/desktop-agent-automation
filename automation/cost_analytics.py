"""Advanced analytics over OpenAI cost metrics logs."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from automation.cost_tracker import DEFAULT_COST_METRICS_PATH


@dataclass(frozen=True)
class CostRecord:
    """Normalized view of a single cost_metrics.jsonl record."""

    timestamp: datetime
    source: str
    event: str
    model: str
    input_tokens: int
    output_tokens: int
    vision_images: int
    token_cost: float
    vision_cost: float
    total_cost: float
    details: Dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CostRecord" | None:
        try:
            timestamp = datetime.fromisoformat(str(raw["timestamp"]))
        except Exception:
            return None
        details = raw.get("details") or {}
        if not isinstance(details, dict):
            try:
                details = dict(details)  # type: ignore[arg-type]
            except Exception:
                details = {}
        return cls(
            timestamp=timestamp,
            source=str(raw.get("source", "unknown")),
            event=str(raw.get("event", "unknown")),
            model=str(raw.get("model", "unknown")),
            input_tokens=int(raw.get("input_tokens", 0) or 0),
            output_tokens=int(raw.get("output_tokens", 0) or 0),
            vision_images=int(raw.get("vision_images", 0) or 0),
            token_cost=float(raw.get("token_cost", 0.0) or 0.0),
            vision_cost=float(raw.get("vision_cost", 0.0) or 0.0),
            total_cost=float(raw.get("total_cost", 0.0) or 0.0),
            details=details,
        )

    @property
    def agent_type(self) -> str:
        return CostAnalytics.classify_agent_type(self.source, self.details)


class CostAnalytics:
    """Generates insights and optimization signals from cost logs."""

    AUTO_ALLOW_LABEL = "Auto-Allow"
    ORCHESTRATOR_LABEL = "Master Orchestrator"
    OTHER_LABEL = "Other Agents"

    # Ordered so the first match wins for classification.
    _AGENT_KEYWORDS: Dict[str, tuple[str, ...]] = {
        AUTO_ALLOW_LABEL: (
            "auto_allow",
            "panel_tracker",
            "panel_review",
            "vs_code_copilot",
            "desktop_auto_allow",
            "panel_followups",
        ),
        ORCHESTRATOR_LABEL: (
            "master_prompt_orchestrator",
            "prompt_orchestrator",
            "prompt_master",
            "master_orchestrator",
        ),
    }

    _PANEL_KEYS = ("panel_title", "panel", "window_title", "panel_id", "assignment")
    _REPO_KEYS = ("repo", "repository", "repo_name", "repository_name")

    def __init__(
        self,
        metrics_path: Path | str | None = None,
        *,
        now: Optional[datetime] = None,
    ) -> None:
        self.metrics_path = Path(metrics_path) if metrics_path else DEFAULT_COST_METRICS_PATH
        self.now = now or datetime.now()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_records(self, *, days: Optional[int] = None) -> List[CostRecord]:
        if not self.metrics_path.exists():
            return []
        cutoff = self.now - timedelta(days=days) if days else None
        records: List[CostRecord] = []
        with self.metrics_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record = CostRecord.from_dict(raw)
                if record is None:
                    continue
                if cutoff and record.timestamp < cutoff:
                    continue
                records.append(record)
        return records

    def generate_report(
        self,
        *,
        days: int = 45,
        panel_limit: int = 10,
        repo_limit: int = 10,
    ) -> Dict[str, Any]:
        records = self.load_records(days=days)
        report: Dict[str, Any] = {
            "generated_at": self.now.isoformat(),
            "timeframe_days": days,
            "records_analyzed": len(records),
            "agent_type_spend": {"daily": [], "weekly": [], "monthly": []},
            "agent_type_totals": {},
            "cost_per_panel": [],
            "cost_per_repo": [],
            "model_usage_distribution": [],
            "trend": {},
            "outliers": [],
            "recommendations": [],
        }
        if not records:
            return report

        report["agent_type_spend"] = {
            "daily": self._spend_by_agent(records, bucket="day"),
            "weekly": self._spend_by_agent(records, bucket="week"),
            "monthly": self._spend_by_agent(records, bucket="month"),
        }
        report["agent_type_totals"] = self._agent_totals(records)
        report["cost_per_panel"] = self._aggregate_by(records, self._extract_panel_name, panel_limit)
        report["cost_per_repo"] = self._aggregate_by(records, self._extract_repo_name, repo_limit)
        report["model_usage_distribution"] = self._model_distribution(records)

        daily_totals = self._daily_totals(records)
        report["trend"] = self._trend(daily_totals)
        report["outliers"] = self._outliers(daily_totals)
        report["recommendations"] = self._recommendations(report)
        return report

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    @classmethod
    def classify_agent_type(cls, source: str, details: Mapping[str, Any]) -> str:
        needle = (source or "").lower()
        for label, keywords in cls._AGENT_KEYWORDS.items():
            if any(keyword in needle for keyword in keywords):
                return label
        detail_source = str(details.get("agent_type", "")).lower()
        for label, keywords in cls._AGENT_KEYWORDS.items():
            if any(keyword in detail_source for keyword in keywords):
                return label
        return cls.OTHER_LABEL

    # ------------------------------------------------------------------
    # Aggregations
    # ------------------------------------------------------------------

    def _agent_totals(self, records: Iterable[CostRecord]) -> Dict[str, Any]:
        totals = defaultdict(lambda: {"cost": 0.0, "calls": 0})
        for record in records:
            bucket = record.agent_type
            totals[bucket]["cost"] += record.total_cost
            totals[bucket]["calls"] += 1
        for payload in totals.values():
            calls = payload["calls"] or 1
            payload["avg_cost_per_call"] = payload["cost"] / calls
        totals["overall"] = {
            "cost": sum(entry["cost"] for entry in totals.values()),
            "calls": sum(entry["calls"] for entry in totals.values()),
        }
        overall_calls = totals["overall"]["calls"] or 1
        totals["overall"]["avg_cost_per_call"] = totals["overall"]["cost"] / overall_calls
        return {label: dict(payload) for label, payload in totals.items()}

    def _spend_by_agent(self, records: Iterable[CostRecord], *, bucket: str) -> List[Dict[str, Any]]:
        breakdown: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for record in records:
            key = self._bucket_key(record.timestamp, bucket)
            breakdown[key][record.agent_type] += record.total_cost
        timeline: List[Dict[str, Any]] = []
        for period in sorted(breakdown.keys()):
            agent_map = dict(breakdown[period])
            total_cost = sum(agent_map.values())
            timeline.append({
                "period": period,
                "total_cost": total_cost,
                "agent_breakdown": agent_map,
            })
        return timeline

    def _aggregate_by(
        self,
        records: Iterable[CostRecord],
        extractor: Any,
        limit: int,
    ) -> List[Dict[str, Any]]:
        buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"cost": 0.0, "calls": 0})
        for record in records:
            label = extractor(record)
            buckets[label]["cost"] += record.total_cost
            buckets[label]["calls"] += 1
        items = []
        for label, payload in buckets.items():
            calls = payload["calls"] or 1
            payload["avg_cost_per_call"] = payload["cost"] / calls
            items.append({"label": label, **payload})
        items.sort(key=lambda row: row["cost"], reverse=True)
        return items[:limit]

    def _model_distribution(self, records: Iterable[CostRecord]) -> List[Dict[str, Any]]:
        stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        for record in records:
            entry = stats[record.model or "unknown"]
            entry["cost"] += record.total_cost
            entry["calls"] += 1
            entry["input_tokens"] += record.input_tokens
            entry["output_tokens"] += record.output_tokens
        rows: List[Dict[str, Any]] = []
        for model, payload in stats.items():
            calls = payload["calls"] or 1
            payload["avg_cost_per_call"] = payload["cost"] / calls
            payload["avg_input_tokens"] = payload["input_tokens"] / calls
            payload["avg_output_tokens"] = payload["output_tokens"] / calls
            rows.append({"model": model, **payload})
        rows.sort(key=lambda row: row["cost"], reverse=True)
        return rows

    def _daily_totals(self, records: Iterable[CostRecord]) -> List[Dict[str, Any]]:
        totals = defaultdict(float)
        for record in records:
            day = record.timestamp.strftime("%Y-%m-%d")
            totals[day] += record.total_cost
        return [{"period": day, "cost": totals[day]} for day in sorted(totals.keys())]

    def _trend(self, daily_totals: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not daily_totals:
            return {}
        costs = [entry["cost"] for entry in daily_totals]
        avg_daily_cost = sum(costs) / len(costs)
        last_week = costs[-7:]
        prev_week = costs[-14:-7]
        seven_day_change_pct: Optional[float] = None
        if last_week and prev_week:
            prev_total = sum(prev_week)
            curr_total = sum(last_week)
            if prev_total > 0:
                seven_day_change_pct = (curr_total - prev_total) / prev_total
        direction = "flat"
        if len(costs) >= 2:
            slope = costs[-1] - costs[0]
            if abs(slope) <= avg_daily_cost * 0.05:
                direction = "flat"
            elif slope > 0:
                direction = "up"
            else:
                direction = "down"
        return {
            "daily_totals": daily_totals,
            "avg_daily_cost": avg_daily_cost,
            "seven_day_change_pct": seven_day_change_pct,
            "trend_direction": direction,
        }

    def _outliers(self, daily_totals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(daily_totals) < 3:
            return []
        values = [entry["cost"] for entry in daily_totals]
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        if math.isclose(stdev, 0.0):
            return []
        threshold = mean + (2 * stdev)
        outliers = []
        for entry in daily_totals:
            if entry["cost"] >= threshold:
                z_score = (entry["cost"] - mean) / stdev
                outliers.append({"period": entry["period"], "cost": entry["cost"], "z_score": z_score})
        return outliers

    def _recommendations(self, report: Dict[str, Any]) -> List[str]:
        recs: List[str] = []
        totals = report.get("agent_type_totals") or {}
        auto_allow = totals.get(self.AUTO_ALLOW_LABEL, {}).get("cost", 0.0)
        orchestrator = totals.get(self.ORCHESTRATOR_LABEL, {}).get("cost", 0.0)
        overall = totals.get("overall", {}).get("cost", 0.0) or 1.0
        if auto_allow / overall > 0.7:
            recs.append("Auto-Allow agents consume over 70% of spend. Review their prompt budgets or cooldowns.")
        if orchestrator / overall > 0.4:
            recs.append("Master Orchestrator usage remains high; consider tightening document selection or batching prompts.")
        trend = report.get("trend", {})
        change_pct = trend.get("seven_day_change_pct")
        if isinstance(change_pct, (int, float)) and change_pct > 0.25:
            recs.append("Seven-day spend climbed more than 25%; ensure recent prompt packs are still required.")
        if report.get("outliers"):
            recs.append("Detected high-spend outlier days; investigate matching log entries for runaway panels.")
        if not recs:
            recs.append("Spend is stable. Continue monitoring automated budgeting thresholds.")
        return recs

    # ------------------------------------------------------------------
    # Extractors
    # ------------------------------------------------------------------

    def _extract_panel_name(self, record: CostRecord) -> str:
        for key in self._PANEL_KEYS:
            value = record.details.get(key)
            if value:
                return str(value)
        return "unattributed-panel"

    def _extract_repo_name(self, record: CostRecord) -> str:
        for key in self._REPO_KEYS:
            value = record.details.get(key)
            if value:
                return str(value)
        panel_name = record.details.get("panel_title") or record.details.get("panel")
        if isinstance(panel_name, str) and panel_name.endswith(" - Visual Studio Code"):
            trimmed = panel_name[: -len(" - Visual Studio Code")]
            pieces = [piece.strip() for piece in trimmed.split(" - ") if piece.strip()]
            if len(pieces) >= 2:
                return pieces[-1]
        return "unattributed-repo"

    @staticmethod
    def _bucket_key(ts: datetime, bucket: str) -> str:
        if bucket == "day":
            return ts.strftime("%Y-%m-%d")
        if bucket == "week":
            iso = ts.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        if bucket == "month":
            return ts.strftime("%Y-%m")
        return "all"
