"""Cost tracking helpers for desktop agent automation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union, List
from collections import defaultdict

from automation.utils import ensure_log_file

DEFAULT_COST_METRICS_PATH = Path(__file__).resolve().parent.parent / "logs" / "cost_metrics.jsonl"
DEFAULT_VISION_COST_PER_IMAGE = float(os.environ.get("COST_TRACKER_VISION_COST_PER_IMAGE", "0.02"))

@dataclass(frozen=True)
class TokenRate:
    """Token rate in dollars per 1k tokens."""

    input_per_1k: float
    output_per_1k: float


DEFAULT_RATES_LAST_UPDATED = datetime(2025, 12, 12)


DEFAULT_MODEL_RATES: Dict[str, TokenRate] = {
    # Approximate placeholder rates (USD per 1k tokens). Override via COST_TRACKER_MODEL_RATES for accuracy (see README).
    "gpt-4o-mini": TokenRate(input_per_1k=0.00045, output_per_1k=0.0009),
    "gpt-4o": TokenRate(input_per_1k=0.001, output_per_1k=0.002),
    "gpt-4-turbo": TokenRate(input_per_1k=0.001, output_per_1k=0.002),
}

_COST_TRACKER_INSTANCE: Optional["CostTracker"] = None


def _parse_model_rates_from_env() -> Dict[str, TokenRate]:
    raw = os.environ.get("COST_TRACKER_MODEL_RATES", "")
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    rates: Dict[str, TokenRate] = {}
    if isinstance(parsed, Mapping):
        for model_name, data in parsed.items():
            if not isinstance(model_name, str) or not isinstance(data, Mapping):
                continue
            try:
                input_rate = float(data.get("input_per_1k", 0))
                output_rate = float(data.get("output_per_1k", 0))
            except (TypeError, ValueError):
                continue
            rates[model_name.lower()] = TokenRate(input_per_1k=input_rate, output_per_1k=output_rate)
    return rates


def _parse_positive_float(raw_value: Optional[str], default: float) -> float:
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def get_cost_tracker() -> "CostTracker":
    """Return the shared cost tracker instance."""
    global _COST_TRACKER_INSTANCE
    if _COST_TRACKER_INSTANCE is None:
        _COST_TRACKER_INSTANCE = CostTracker()
    return _COST_TRACKER_INSTANCE


class CostTracker:
    """Tracks API spend and writes records as JSON lines."""

    def __init__(
        self,
        *,
        metrics_path: Path | str | None = None,
        model_rates: Optional[Mapping[str, TokenRate]] = None,
        vision_cost_per_image: Optional[float] = None,
    ) -> None:
        self.metrics_path = Path(metrics_path) if metrics_path else DEFAULT_COST_METRICS_PATH
        env_rates = _parse_model_rates_from_env()
        combined: Dict[str, TokenRate] = {
            key.lower(): rate for key, rate in DEFAULT_MODEL_RATES.items()
        }
        combined.update(env_rates)
        if model_rates:
            combined.update({k.lower(): v for k, v in model_rates.items()})
        self.token_rates = combined
        self.default_rate = TokenRate(input_per_1k=0.0, output_per_1k=0.0)
        env_vision_cost = _parse_positive_float(
            os.environ.get("COST_TRACKER_VISION_COST_PER_IMAGE"), DEFAULT_VISION_COST_PER_IMAGE
        )
        self.vision_cost_per_image = vision_cost_per_image if vision_cost_per_image is not None else env_vision_cost
        self._session_totals: Dict[str, Union[int, float]] = {
            "text_events": 0,
            "vision_events": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "vision_images": 0,
            "token_cost": 0.0,
            "vision_cost": 0.0,
            "total_cost": 0.0,
        }

    def _find_rate(self, model_name: str) -> TokenRate:
        current = model_name.lower()
        best_match: Optional[TokenRate] = None
        best_key: Optional[str] = None
        for key, rate in self.token_rates.items():
            if current.startswith(key):
                if best_key is None or len(key) > len(best_key):
                    best_match = rate
                    best_key = key
        return best_match or self.default_rate

    @staticmethod
    def _normalize_usage(usage: Any) -> Dict[str, Any]:
        if usage is None:
            return {}
        if isinstance(usage, Mapping):
            return dict(usage)
        if hasattr(usage, "to_dict"):
            try:
                return usage.to_dict()
            except Exception:
                pass
        if hasattr(usage, "__dict__"):
            return dict(getattr(usage, "__dict__", {}))
        return {}

    @staticmethod
    def _extract_token_counts(usage_data: Mapping[str, Any]) -> Tuple[int, int]:
        input_tokens = int(usage_data.get("input_tokens") or 0)
        output_tokens = int(usage_data.get("output_tokens") or 0)
        return input_tokens, output_tokens

    def _estimate_token_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rate = self._find_rate(model or "")
        return (input_tokens / 1000) * rate.input_per_1k + (output_tokens / 1000) * rate.output_per_1k

    def _append_record(self, record: Dict[str, Any]) -> None:
        try:
            ensure_log_file(self.metrics_path)
            with self.metrics_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record) + "\n")
        except Exception as e:
            import sys
            print(f"Warning: Failed to write cost record: {e}", file=sys.stderr)

    def _build_record(
        self,
        *,
        source: str,
        event: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        vision_images: int,
        token_cost: float,
        vision_cost: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        total_cost = token_cost + vision_cost
        return {
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "event": event,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "vision_images": vision_images,
            "token_cost": round(token_cost, 6),
            "vision_cost": round(vision_cost, 6),
            "total_cost": round(total_cost, 6),
            "details": details or {},
        }

    def _update_session_totals(self, record: Dict[str, Any], *, is_vision: bool) -> None:
        summary = self._session_totals
        if is_vision:
            summary["vision_events"] += 1
            summary["vision_images"] += record.get("vision_images", 0)
        else:
            summary["text_events"] += 1
        summary["input_tokens"] += record.get("input_tokens", 0)
        summary["output_tokens"] += record.get("output_tokens", 0)
        summary["token_cost"] += record.get("token_cost", 0.0)
        summary["vision_cost"] += record.get("vision_cost", 0.0)
        summary["total_cost"] += record.get("total_cost", 0.0)

    def record_text_usage(
        self,
        *,
        source: str,
        event: str,
        model: str,
        usage: Any | None = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        usage_data = self._normalize_usage(usage)
        input_tokens, output_tokens = self._extract_token_counts(usage_data)
        token_cost = self._estimate_token_cost(model, input_tokens, output_tokens)
        record = self._build_record(
            source=source,
            event=event,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            vision_images=0,
            token_cost=token_cost,
            vision_cost=0.0,
            details={"usage": usage_data, **(details or {})},
        )
        self._append_record(record)
        self._update_session_totals(record, is_vision=False)

    def record_vision_usage(
        self,
        *,
        source: str,
        event: str,
        model: str,
        image_count: int = 1,
        usage: Any | None = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        usage_data = self._normalize_usage(usage)
        input_tokens, output_tokens = self._extract_token_counts(usage_data)
        token_cost = self._estimate_token_cost(model, input_tokens, output_tokens)
        vision_cost = image_count * self.vision_cost_per_image
        record = self._build_record(
            source=source,
            event=event,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            vision_images=image_count,
            token_cost=token_cost,
            vision_cost=vision_cost,
            details={"usage": usage_data, **(details or {})},
        )
        self._append_record(record)
        self._update_session_totals(record, is_vision=True)

    def record_copilot_status(
        self,
        *,
        percentage: Optional[float],
        normalized_ratio: Optional[float],
        calendar_progress: float,
        alert: Optional[str],
        timestamp: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record Copilot status observations without affecting token totals."""

        record_time = timestamp.isoformat() if timestamp else datetime.now().isoformat()
        record: Dict[str, Any] = {
            "timestamp": record_time,
            "source": "copilot_usage_monitor",
            "event": "copilot_status",
            "model": "copilot_status",
            "input_tokens": 0,
            "output_tokens": 0,
            "vision_images": 0,
            "token_cost": 0.0,
            "vision_cost": 0.0,
            "total_cost": 0.0,
            "details": {
                "percentage": percentage,
                "normalized_ratio": normalized_ratio,
                "calendar_progress": round(calendar_progress, 4),
                "alert": alert,
                **(details or {}),
            },
        }
        self._append_record(record)

    def get_session_totals(self) -> Dict[str, Union[int, float]]:
        """Return aggregated metrics for the current process lifetime."""
        return dict(self._session_totals)

    def reset_session_totals(self) -> None:
        """Reset the in-memory session totals (does not touch log files)."""
        for key in self._session_totals:
            self._session_totals[key] = 0.0 if isinstance(self._session_totals[key], float) else 0

    def estimate_cost(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        image_count: int = 0,
    ) -> float:
        """
        Estimate cost for a hypothetical API call without recording it.

        Args:
            model: Model name
            input_tokens: Estimated input tokens
            output_tokens: Estimated output tokens
            image_count: Number of images (for vision calls)

        Returns:
            Estimated cost in dollars
        """
        token_cost = self._estimate_token_cost(model, input_tokens, output_tokens)
        vision_cost = image_count * self.vision_cost_per_image
        return token_cost + vision_cost

    def get_budget_limits(self) -> Dict[str, float]:
        """Get current budget limits from environment variables."""
        return {
            "daily_limit": float(os.environ.get("COST_TRACKER_DAILY_LIMIT", "10.0")),
            "weekly_limit": float(os.environ.get("COST_TRACKER_WEEKLY_LIMIT", "50.0")),
            "monthly_limit": float(os.environ.get("COST_TRACKER_MONTHLY_LIMIT", "200.0")),
        }

    def check_budget_alerts(self) -> List[str]:
        """
        Check if any budget limits are approaching or exceeded.

        Returns:
            List of alert messages
        """
        alerts = []
        limits = self.get_budget_limits()

        # Calculate current spending
        daily_cost = self._calculate_period_cost(timedelta(days=1))
        weekly_cost = self._calculate_period_cost(timedelta(days=7))
        monthly_cost = self._calculate_period_cost(timedelta(days=30))

        # Check thresholds (80% warning, 100% critical)
        if daily_cost >= limits["daily_limit"]:
            alerts.append(f"DAILY BUDGET EXCEEDED: ${daily_cost:.2f} >= ${limits['daily_limit']:.2f}")
        elif daily_cost >= limits["daily_limit"] * 0.8:
            alerts.append(f"DAILY BUDGET WARNING: ${daily_cost:.2f} / ${limits['daily_limit']:.2f} ({daily_cost/limits['daily_limit']:.1%})")

        if weekly_cost >= limits["weekly_limit"]:
            alerts.append(f"WEEKLY BUDGET EXCEEDED: ${weekly_cost:.2f} >= ${limits['weekly_limit']:.2f}")
        elif weekly_cost >= limits["weekly_limit"] * 0.8:
            alerts.append(f"WEEKLY BUDGET WARNING: ${weekly_cost:.2f} / ${limits['weekly_limit']:.2f} ({weekly_cost/limits['weekly_limit']:.1%})")

        if monthly_cost >= limits["monthly_limit"]:
            alerts.append(f"MONTHLY BUDGET EXCEEDED: ${monthly_cost:.2f} >= ${limits['monthly_limit']:.2f}")
        elif monthly_cost >= limits["monthly_limit"] * 0.8:
            alerts.append(f"MONTHLY BUDGET WARNING: ${monthly_cost:.2f} / ${limits['monthly_limit']:.2f} ({monthly_cost/limits['monthly_limit']:.1%})")

        return alerts

    def _calculate_period_cost(self, period: timedelta) -> float:
        """Calculate total cost for the given time period."""
        if not self.metrics_path.exists():
            return 0.0

        cutoff = datetime.now() - period
        total_cost = 0.0

        try:
            with self.metrics_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        record_time = datetime.fromisoformat(record["timestamp"])
                        if record_time >= cutoff:
                            total_cost += record.get("total_cost", 0.0)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except Exception:
            pass

        return total_cost

    def get_cost_report(
        self,
        *,
        days: int = 7,
        group_by: str = "day",  # "day", "model", "source", "event"
    ) -> Dict[str, Any]:
        """
        Generate a cost report for the specified period.

        Args:
            days: Number of days to look back
            group_by: How to group the results

        Returns:
            Dictionary with cost breakdown
        """
        if not self.metrics_path.exists():
            return {"error": "No cost metrics file found"}

        cutoff = datetime.now() - timedelta(days=days)
        records = []

        # Load records
        try:
            with self.metrics_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        record_time = datetime.fromisoformat(record["timestamp"])
                        if record_time >= cutoff:
                            records.append(record)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except Exception as e:
            return {"error": f"Failed to read metrics: {e}"}

        if not records:
            return {"total_cost": 0.0, "record_count": 0, "breakdown": {}}

        # Group records
        from typing import DefaultDict
        breakdown: DefaultDict[str, Dict[str, Union[float, int]]] = defaultdict(lambda: {"cost": 0.0, "count": 0, "tokens_in": 0, "tokens_out": 0, "images": 0})

        for record in records:
            key = self._get_group_key(record, group_by)
            breakdown[key]["cost"] += record.get("total_cost", 0.0)
            breakdown[key]["count"] += 1
            breakdown[key]["tokens_in"] += record.get("input_tokens", 0)
            breakdown[key]["tokens_out"] += record.get("output_tokens", 0)
            breakdown[key]["images"] += record.get("vision_images", 0)

        total_cost = sum(record.get("total_cost", 0.0) for record in records)

        return {
            "total_cost": round(total_cost, 6),
            "record_count": len(records),
            "period_days": days,
            "breakdown": dict(breakdown),
        }

    def _get_group_key(self, record: Dict[str, Any], group_by: str) -> str:
        """Get the grouping key for a record."""
        if group_by == "day":
            timestamp = datetime.fromisoformat(record["timestamp"])
            return timestamp.strftime("%Y-%m-%d")
        elif group_by == "model":
            return record.get("model", "unknown")
        elif group_by == "source":
            return record.get("source", "unknown")
        elif group_by == "event":
            return record.get("event", "unknown")
        else:
            return "all"

    def print_cost_report(self, days: int = 7) -> None:
        """Print a formatted cost report."""
        report = self.get_cost_report(days=days)

        if "error" in report:
            print(f"Error generating report: {report['error']}")
            return

        print(f"\n{'='*60}")
        print(f"OPENAI COST REPORT (Last {days} days)")
        print(f"{'='*60}")
        print(f"Total Cost: ${report['total_cost']:.4f}")
        print(f"Total API Calls: {report['record_count']}")
        print()

        if report["breakdown"]:
            print("Breakdown by Day:")
            print("-" * 40)
            for day, data in sorted(report["breakdown"].items()):
                print(f"  {day}: ${data['cost']:.4f} ({data['count']} calls)")
            print()

        # Check for alerts
        alerts = self.check_budget_alerts()
        if alerts:
            print("⚠️  BUDGET ALERTS:")
            print("-" * 40)
            for alert in alerts:
                print(f"  {alert}")
            print()

        print(f"{'='*60}\n")
