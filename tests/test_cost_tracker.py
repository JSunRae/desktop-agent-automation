"""Unit tests for the cost tracking helper."""

from __future__ import annotations

import json
from pathlib import Path

from automation.cost_tracker import CostTracker, TokenRate


def test_record_text_usage_calculates_token_cost(tmp_path: Path) -> None:
    metrics_file = tmp_path / "cost_metrics.jsonl"
    tracker = CostTracker(
        metrics_path=metrics_file,
        model_rates={"test-model": TokenRate(input_per_1k=1.0, output_per_1k=2.0)},
    )

    tracker.record_text_usage(
        source="tests",
        event="prompt",
        model="test-model",
        usage={"input_tokens": 100, "output_tokens": 200},
    )

    lines = metrics_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["input_tokens"] == 100
    assert record["output_tokens"] == 200
    assert abs(record["token_cost"] - 0.5) < 1e-6
    assert record["vision_cost"] == 0.0
    assert abs(record["total_cost"] - 0.5) < 1e-6


def test_record_vision_usage_includes_per_image_cost(tmp_path: Path) -> None:
    metrics_file = tmp_path / "vision_cost.jsonl"
    tracker = CostTracker(
        metrics_path=metrics_file,
        model_rates={"gpt-vision": TokenRate(input_per_1k=0.0, output_per_1k=0.0)},
        vision_cost_per_image=0.05,
    )

    tracker.record_vision_usage(
        source="tests",
        event="vision",
        model="gpt-vision",
        image_count=2,
        usage={"input_tokens": 50, "output_tokens": 50},
    )

    record = json.loads(metrics_file.read_text(encoding="utf-8").strip())
    assert record["vision_cost"] == 0.1
    assert record["token_cost"] == 0
    assert abs(record["total_cost"] - 0.1) < 1e-6


def test_session_totals_accumulate_and_reset(tmp_path: Path) -> None:
    metrics_file = tmp_path / "session_cost.jsonl"
    tracker = CostTracker(
        metrics_path=metrics_file,
        model_rates={"mix": TokenRate(input_per_1k=1.0, output_per_1k=1.0)},
        vision_cost_per_image=0.1,
    )

    tracker.record_text_usage(
        source="tests",
        event="text",
        model="mix",
        usage={"input_tokens": 200, "output_tokens": 100},
    )
    tracker.record_vision_usage(
        source="tests",
        event="vision",
        model="mix",
        image_count=2,
        usage={"input_tokens": 50, "output_tokens": 25},
    )

    totals = tracker.get_session_totals()
    assert totals["text_events"] == 1
    assert totals["vision_events"] == 1
    assert totals["vision_images"] == 2
    assert totals["input_tokens"] == 250
    assert totals["output_tokens"] == 125
    assert totals["token_cost"] > 0
    assert totals["vision_cost"] == 0.2

    tracker.reset_session_totals()
    reset_totals = tracker.get_session_totals()
    assert all(value == 0 or value == 0.0 for value in reset_totals.values())


def test_estimate_cost_calculates_correctly(tmp_path: Path) -> None:
    tracker = CostTracker(
        metrics_path=tmp_path / "estimate.jsonl",
        model_rates={"test": TokenRate(input_per_1k=1.0, output_per_1k=2.0)},
        vision_cost_per_image=0.1,
    )

    # Test text-only cost
    text_cost = tracker.estimate_cost(
        model="test",
        input_tokens=1000,
        output_tokens=500,
        image_count=0,
    )
    assert abs(text_cost - 2.0) < 1e-6  # (1000/1000)*1.0 + (500/1000)*2.0 = 1.0 + 1.0 = 2.0

    # Test with vision
    vision_cost = tracker.estimate_cost(
        model="test",
        input_tokens=1000,
        output_tokens=500,
        image_count=2,
    )
    assert abs(vision_cost - 2.2) < 1e-6  # 2.0 + 2*0.1 = 2.2


def test_budget_alerts_trigger_at_thresholds(tmp_path: Path, monkeypatch) -> None:
    # Set low budget limits for testing
    monkeypatch.setenv("COST_TRACKER_DAILY_LIMIT", "1.0")
    monkeypatch.setenv("COST_TRACKER_WEEKLY_LIMIT", "5.0")
    
    metrics_file = tmp_path / "budget.jsonl"
    tracker = CostTracker(metrics_path=metrics_file)
    
    # Record some usage
    tracker.record_text_usage(
        source="test",
        event="budget_test",
        model="gpt-4o-mini",
        usage={"input_tokens": 1000, "output_tokens": 1000},  # ~$0.005
    )
    
    alerts = tracker.check_budget_alerts()
    # Should not trigger alerts for small amounts
    assert len(alerts) == 0
    
    # Add more usage to trigger alert (need ~$0.80+ for 80% of $1.00 limit)
    for _ in range(600):  # Add ~$0.81 in usage with higher token counts
        tracker.record_text_usage(
            source="test",
            event="budget_test",
            model="gpt-4o-mini",
            usage={"input_tokens": 2000, "output_tokens": 2000},  # Higher token count
        )
    
    alerts = tracker.check_budget_alerts()
    assert len(alerts) > 0
    assert "WARNING" in alerts[0] or "EXCEEDED" in alerts[0]


def test_cost_report_generation(tmp_path: Path) -> None:
    metrics_file = tmp_path / "report.jsonl"
    tracker = CostTracker(metrics_path=metrics_file)
    
    # Add some test data
    tracker.record_text_usage(
        source="test_source",
        event="test_event",
        model="gpt-4o-mini",
        usage={"input_tokens": 100, "output_tokens": 50},
    )
    
    report = tracker.get_cost_report(days=1)
    assert "total_cost" in report
    assert "record_count" in report
    assert "breakdown" in report
    assert report["record_count"] == 1
    assert report["total_cost"] > 0
