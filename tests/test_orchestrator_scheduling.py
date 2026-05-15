from __future__ import annotations

from datetime import datetime, timedelta

from automation import orchestrator


class _MonitorStub:
    def __init__(self, *, alert: str | None = None) -> None:
        self.alert = alert
        self.calls = 0

    def poll_once(self):
        self.calls += 1
        return type(
            "Snapshot",
            (),
            {
                "alert": self.alert,
                "percentage": 55.0,
                "calendar_progress": 50.0,
            },
        )()


def test_maybe_poll_copilot_usage_skips_before_interval(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "ENABLE_COPILOT_USAGE_MONITOR", True)
    monkeypatch.setattr(orchestrator, "COPILOT_USAGE_MONITOR_INTERVAL_SECONDS", 1800.0)

    now = datetime(2026, 4, 25, 11, 0, 0)
    last = now - timedelta(minutes=10)
    monitor = _MonitorStub()

    updated = orchestrator._maybe_poll_copilot_usage(now=now, last_checked_at=last, monitor=monitor)

    assert updated == last
    assert monitor.calls == 0


def test_maybe_poll_copilot_usage_polls_after_interval(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "ENABLE_COPILOT_USAGE_MONITOR", True)
    monkeypatch.setattr(orchestrator, "COPILOT_USAGE_MONITOR_INTERVAL_SECONDS", 900.0)

    now = datetime(2026, 4, 25, 11, 30, 0)
    last = now - timedelta(minutes=20)
    monitor = _MonitorStub(alert="WARNING: Copilot usage pace is above calendar progress")

    updated = orchestrator._maybe_poll_copilot_usage(now=now, last_checked_at=last, monitor=monitor)

    assert updated == now
    assert monitor.calls == 1


def test_maybe_poll_copilot_usage_handles_monitor_failure(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "ENABLE_COPILOT_USAGE_MONITOR", True)
    monkeypatch.setattr(orchestrator, "COPILOT_USAGE_MONITOR_INTERVAL_SECONDS", 900.0)

    messages: list[str] = []
    monkeypatch.setattr(orchestrator, "log_verbose", messages.append)

    class _BrokenMonitor:
        def poll_once(self):
            raise RuntimeError("uia unavailable")

    now = datetime(2026, 4, 25, 11, 45, 0)
    last = now - timedelta(minutes=20)

    updated = orchestrator._maybe_poll_copilot_usage(now=now, last_checked_at=last, monitor=_BrokenMonitor())

    assert updated == now
    assert any("Copilot usage monitor poll failed" in message for message in messages)