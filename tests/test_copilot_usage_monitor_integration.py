from __future__ import annotations

import sys
import threading
import time
from datetime import datetime

import pytest

import run_automation
from automation import orchestrator


class _RateMonitorStub:
    def check(self, is_paused: bool) -> None:
        return None


class _BackgroundMonitorStub:
    instances: list["_BackgroundMonitorStub"] = []

    def __init__(self, *, cost_tracker=None, interval_seconds: float = 300.0, **kwargs) -> None:
        self.interval_seconds = interval_seconds
        self.start_calls = 0
        self.stop_calls = 0
        self.poll_calls = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.polled = threading.Event()
        _BackgroundMonitorStub.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_calls += 1
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def poll_once(self):
        self.poll_calls += 1
        self.polled.set()
        return type(
            "Snapshot",
            (),
            {
                "alert": None,
                "percentage": None,
                "calendar_progress": 0.0,
            },
        )()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(0.02)


def _configure_minimal_run_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "load_allow_events", lambda: None)
    monkeypatch.setattr(orchestrator, "get_tracker", lambda: None)
    monkeypatch.setattr(orchestrator, "RateMonitor", lambda: _RateMonitorStub())
    monkeypatch.setattr(orchestrator, "check_hotkeys_polled", lambda: None)
    monkeypatch.setattr(orchestrator, "check_mouse_interrupts", lambda: None)
    monkeypatch.setattr(orchestrator, "is_paused", lambda: False)
    monkeypatch.setattr(orchestrator, "extra_wait_until", lambda: datetime.min)
    monkeypatch.setattr(orchestrator, "is_keyboard_activity_detected", lambda: False)
    monkeypatch.setattr(orchestrator, "AUTO_PAUSE_ON_KEYBOARD_INPUT", False)
    monkeypatch.setattr(orchestrator, "AUTO_PAUSE_ON_TYPING", False)
    monkeypatch.setattr(orchestrator, "ENABLE_VSCODE_TOAST_SHORTCUT", False)
    monkeypatch.setattr(orchestrator, "USE_CACHED_HANDLES", True)
    monkeypatch.setattr(orchestrator, "should_refresh_cache", lambda now: False)
    monkeypatch.setattr(orchestrator, "get_cached_vscode_windows", lambda: [])
    monkeypatch.setattr(orchestrator, "increment_desktop_cycles", lambda: None)
    monkeypatch.setattr(orchestrator, "find_all_vscode_windows", lambda: [])
    monkeypatch.setattr(orchestrator, "process_finished_panels_with_prompts", lambda windows: None)
    monkeypatch.setattr(orchestrator, "is_in_cooldown", lambda now: False)
    monkeypatch.setattr(orchestrator, "is_try_again_cooldown_active", lambda: False)
    monkeypatch.setattr(orchestrator, "MIN_SCAN_INTERVAL_SECONDS", 0.01)


def test_run_loop_starts_usage_monitor_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _BackgroundMonitorStub.instances.clear()
    _configure_minimal_run_loop(monkeypatch)
    monkeypatch.setattr(orchestrator, "ENABLE_COPILOT_USAGE_MONITOR", True)
    monkeypatch.setattr(orchestrator, "COPILOT_USAGE_MONITOR_INTERVAL_SECONDS", 7.5)
    monkeypatch.setattr(orchestrator, "CopilotUsageMonitor", _BackgroundMonitorStub)
    monkeypatch.setattr(orchestrator, "sleep_with_hotkey_checks", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    try:
        with pytest.raises(KeyboardInterrupt):
            orchestrator.run_main_loop(desktops_list=[0])
    finally:
        orchestrator._stop_copilot_usage_monitor()

    assert len(_BackgroundMonitorStub.instances) == 1
    monitor = _BackgroundMonitorStub.instances[0]
    assert monitor.start_calls == 1
    assert monitor.interval_seconds == 7.5


def test_run_loop_monitor_polls_without_copilot_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    _BackgroundMonitorStub.instances.clear()
    _configure_minimal_run_loop(monkeypatch)
    monkeypatch.setattr(orchestrator, "ENABLE_COPILOT_USAGE_MONITOR", True)
    monkeypatch.setattr(orchestrator, "COPILOT_USAGE_MONITOR_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(orchestrator, "CopilotUsageMonitor", _BackgroundMonitorStub)

    def _sleep_and_interrupt(seconds: float) -> None:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if _BackgroundMonitorStub.instances and _BackgroundMonitorStub.instances[0].poll_calls >= 2:
                raise KeyboardInterrupt
            time.sleep(0.01)
        raise AssertionError("background monitor never polled")

    monkeypatch.setattr(orchestrator, "sleep_with_hotkey_checks", _sleep_and_interrupt)

    try:
        with pytest.raises(KeyboardInterrupt):
            orchestrator.run_main_loop(desktops_list=[0])
    finally:
        orchestrator._stop_copilot_usage_monitor()

    assert len(_BackgroundMonitorStub.instances) == 1
    assert _BackgroundMonitorStub.instances[0].poll_calls >= 2


def test_main_stops_usage_monitor_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_calls: list[bool] = []

    def _raise_keyboard_interrupt() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(run_automation, "_stop_copilot_usage_monitor", lambda: stop_calls.append(True))
    monkeypatch.setattr(run_automation, "TASK_DISCOVERY_AUTOSTART", False)
    monkeypatch.setattr(run_automation, "print_hotkey_info", lambda: None)
    monkeypatch.setattr(run_automation, "load_allow_events", lambda: None)
    monkeypatch.setattr(run_automation, "save_allow_events", lambda: None)
    monkeypatch.setattr(run_automation, "get_session", lambda: type("Session", (), {"print_summary": lambda self: None})())
    monkeypatch.setattr(run_automation, "get_tracker", lambda: type("Tracker", (), {"save_state": lambda self: None})())
    monkeypatch.setattr(run_automation, "run_main_loop", _raise_keyboard_interrupt)
    monkeypatch.setattr(sys, "argv", ["run_automation.py"])

    run_automation.main()

    assert stop_calls == [True]