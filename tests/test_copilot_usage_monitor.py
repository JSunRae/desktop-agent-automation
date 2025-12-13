"""Integration tests for the Copilot usage monitor."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import pytest

from automation.copilot_usage_monitor import CopilotUsageMonitor
from automation.cost_tracker import CostTracker


class DummyControl:
    """A minimal stand-in for a UIA control."""

    def __init__(self, name: str = "", automation_id: str = "", children: List["DummyControl"] | None = None):
        self.Name = name
        self.AutomationId = automation_id
        self._children = children or []

    def GetChildren(self) -> List["DummyControl"]:
        return self._children


def _read_last_record(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fp:
        lines = [line.strip() for line in fp if line.strip()]
    assert lines, "No records were written"
    return json.loads(lines[-1])


def test_monitor_records_percentage_and_normalized_ratio(tmp_path: Path):
    fixed_time = datetime(2025, 12, 16, 12, 0, 0)
    percentage_control = DummyControl("Copilot status 42%", "chat.statusBarEntry")
    root = DummyControl("Root", children=[DummyControl("Status bar", children=[percentage_control])])

    metrics_path = tmp_path / "copilot_cost.jsonl"
    tracker = CostTracker(metrics_path=metrics_path)
    monitor = CopilotUsageMonitor(
        root_provider=lambda: root,  # type: ignore[return-value]
        cost_tracker=tracker,
        time_provider=lambda: fixed_time,
        logger=lambda message: None,
    )

    snapshot = monitor.poll_once()
    assert snapshot.percentage == pytest.approx(42.0)

    # Expect normalized ratio to be percentage / (progress * 100)
    month_start = datetime(2025, 12, 1)
    month_end = month_start + timedelta(days=31)
    expected_progress = ((fixed_time - month_start).total_seconds()) / ((month_end - month_start).total_seconds())
    assert snapshot.calendar_progress == pytest.approx(expected_progress * 100)
    expected_ratio = 42.0 / (max(expected_progress * 100, 1e-6))
    assert snapshot.normalized_ratio == pytest.approx(expected_ratio, rel=1e-4)
    assert snapshot.alert is None

    record = _read_last_record(metrics_path)
    assert record["source"] == "copilot_usage_monitor"
    assert record["event"] == "copilot_status"
    assert record["details"]["percentage"] == pytest.approx(42.0)
    assert record["details"]["normalized_ratio"] == pytest.approx(expected_ratio, rel=1e-4)


def test_monitor_logs_alert_when_ahead_of_schedule(tmp_path: Path):
    fixed_time = datetime(2025, 12, 16, 12, 0, 0)
    ratio_control = DummyControl("Copilot status 90%", "chat.statusBarEntry")
    root = DummyControl("Root", children=[ratio_control])

    metrics_path = tmp_path / "copilot_cost_alert.jsonl"
    tracker = CostTracker(metrics_path=metrics_path)
    log_messages: List[str] = []
    monitor = CopilotUsageMonitor(
        root_provider=lambda: root,  # type: ignore[return-value]
        cost_tracker=tracker,
        time_provider=lambda: fixed_time,
        logger=log_messages.append,
        warning_threshold=1.0,
        critical_threshold=1.2,
    )

    snapshot = monitor.poll_once()
    assert snapshot.alert is not None
    assert "CRITICAL" in snapshot.alert
    assert log_messages
    assert any("CRITICAL" in message for message in log_messages)

    record = _read_last_record(metrics_path)
    assert record["details"]["alert"] == snapshot.alert