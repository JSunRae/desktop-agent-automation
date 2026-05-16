from __future__ import annotations

from datetime import datetime, timedelta

from automation.core import hotkeys


def _reset_hotkey_mouse_state() -> None:
    hotkeys._is_paused = False
    hotkeys._is_auto_paused = False
    hotkeys._extra_wait_until = datetime.min
    hotkeys._last_mouse_position = None
    hotkeys._mouse_pause_until = None
    hotkeys._mouse_pause_active = False
    hotkeys._physical_mouse_anchor = None
    hotkeys._drift_pause_active = False
    hotkeys._drift_pause_until = None
    hotkeys._drift_last_pos = None
    hotkeys._drift_next_check_at = datetime.min


def test_stale_expected_cursor_does_not_trigger_physical_mouse_pause(monkeypatch) -> None:
    _reset_hotkey_mouse_state()
    hotkeys._last_mouse_position = (500, 500)
    hotkeys._physical_mouse_anchor = (500, 500)

    spoken: list[str] = []
    monkeypatch.setattr(hotkeys, "AUTO_PAUSE_ON_CURSOR_DRIFT", False)
    monkeypatch.setattr(hotkeys, "get_cursor_pos", lambda: (500, 500))
    monkeypatch.setattr(hotkeys, "get_expected_cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(
        hotkeys,
        "get_last_automation_cursor_set_at",
        lambda: datetime.now() - timedelta(seconds=5),
    )
    monkeypatch.setattr(hotkeys, "speak", lambda message: spoken.append(message))

    status = hotkeys.check_mouse_interrupts()

    assert status is None
    assert hotkeys._mouse_pause_active is False
    assert hotkeys.extra_wait_until() == datetime.min
    assert spoken == []


def test_recent_automation_cursor_move_resets_mouse_baselines(monkeypatch) -> None:
    _reset_hotkey_mouse_state()
    hotkeys._last_mouse_position = (0, 0)
    hotkeys._physical_mouse_anchor = (0, 0)

    spoken: list[str] = []
    current_pos = (640, 640)
    monkeypatch.setattr(hotkeys, "AUTO_PAUSE_ON_CURSOR_DRIFT", False)
    monkeypatch.setattr(hotkeys, "get_cursor_pos", lambda: current_pos)
    monkeypatch.setattr(hotkeys, "get_expected_cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(hotkeys, "get_last_automation_cursor_set_at", lambda: datetime.now())
    monkeypatch.setattr(hotkeys, "speak", lambda message: spoken.append(message))

    status = hotkeys.check_mouse_interrupts()

    assert status is None
    assert hotkeys._mouse_pause_active is False
    assert hotkeys._last_mouse_position == current_pos
    assert hotkeys._physical_mouse_anchor == current_pos
    assert spoken == []


def test_single_physical_mouse_pause_speaks_specific_reason_once(monkeypatch) -> None:
    _reset_hotkey_mouse_state()
    hotkeys._last_mouse_position = (0, 0)
    hotkeys._physical_mouse_anchor = (0, 0)

    spoken: list[str] = []
    monkeypatch.setattr(hotkeys, "AUTO_PAUSE_ON_CURSOR_DRIFT", False)
    monkeypatch.setattr(hotkeys, "get_cursor_pos", lambda: (240, 240))
    monkeypatch.setattr(hotkeys, "get_expected_cursor_pos", lambda: (999, 999))
    monkeypatch.setattr(hotkeys, "get_last_automation_cursor_set_at", lambda: None)
    monkeypatch.setattr(hotkeys, "speak", lambda message: spoken.append(message))

    status = hotkeys.check_mouse_interrupts()

    assert status is None
    assert hotkeys._mouse_pause_active is True
    assert hotkeys.extra_wait_until() > datetime.now()
    assert hotkeys._physical_mouse_anchor == (240, 240)
    assert spoken == ["Mouse movement detected"]
