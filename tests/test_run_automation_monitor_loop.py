from __future__ import annotations

import sys
import threading
import time

import run_automation


class _DummySession:
    def print_summary(self) -> None:
        pass


class _DummyTracker:
    def save_state(self) -> None:
        pass


def test_monitor_loop_polls_and_stops():
    poll_count = 0
    polled = threading.Event()

    class _FakeMonitor:
        def poll_once(self) -> None:
            nonlocal poll_count
            poll_count += 1
            polled.set()

    stop = run_automation._start_copilot_usage_monitor_loop(
        enabled=True,
        interval_seconds=0.1,
        monitor_factory=lambda: _FakeMonitor(),
    )

    assert stop is not None
    assert polled.wait(timeout=1.0)

    stop()
    before = poll_count
    time.sleep(0.25)
    assert poll_count == before


def test_monitor_loop_logs_failures_and_continues(capsys):
    poll_count = 0
    recovered = threading.Event()

    class _FlakyMonitor:
        def poll_once(self) -> None:
            nonlocal poll_count
            poll_count += 1
            if poll_count == 1:
                raise RuntimeError("boom")
            recovered.set()

    stop = run_automation._start_copilot_usage_monitor_loop(
        enabled=True,
        interval_seconds=0.1,
        monitor_factory=lambda: _FlakyMonitor(),
    )

    assert stop is not None
    assert recovered.wait(timeout=1.5)

    stop()
    captured = capsys.readouterr()
    assert "Copilot usage monitor poll failed" in captured.err
    assert poll_count >= 2


def test_main_starts_and_stops_monitor_loop(monkeypatch):
    stop_calls: list[bool] = []

    def _raise_keyboard_interrupt() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(run_automation, "_stop_copilot_usage_monitor", lambda: stop_calls.append(True))
    monkeypatch.setattr(run_automation, "TASK_DISCOVERY_AUTOSTART", False)
    monkeypatch.setattr(run_automation, "print_hotkey_info", lambda: None)
    monkeypatch.setattr(run_automation, "load_allow_events", lambda: None)
    monkeypatch.setattr(run_automation, "save_allow_events", lambda: None)
    monkeypatch.setattr(run_automation, "get_session", lambda: _DummySession())
    monkeypatch.setattr(run_automation, "get_tracker", lambda: _DummyTracker())
    monkeypatch.setattr(run_automation, "run_main_loop", _raise_keyboard_interrupt)
    monkeypatch.setattr(sys, "argv", ["run_automation.py"])

    run_automation.main()

    assert len(stop_calls) == 1
