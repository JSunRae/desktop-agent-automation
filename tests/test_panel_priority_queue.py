from datetime import datetime
from types import SimpleNamespace

from automation.panel_state import PanelState
from automation.panel_tracker_core import PanelTracker, PanelStatus, _REPO_PRIORITY_MAP


def make_panel(repo_name: str, status: PanelStatus) -> PanelState:
    # Minimal PanelState required for priority computation.
    now = datetime.now()
    return PanelState(
        window_title=f"Dummy - {repo_name} - Visual Studio Code",
        panel_id="panel-1",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        repo_name=repo_name,
        status=status,
    )


def test_sort_windows_by_priority_uses_repo_weights_and_status(monkeypatch):
    # Give one repo a higher intrinsic importance.
    _REPO_PRIORITY_MAP.clear()
    _REPO_PRIORITY_MAP.update({"important": 2.0, "other": 1.0})

    # Avoid touching on-disk state when constructing the tracker.
    monkeypatch.setattr(PanelTracker, "_load_state", lambda self: None, raising=False)

    tracker = PanelTracker()

    # Seed two panels with different repos and statuses.
    important_panel = make_panel("important", PanelStatus.WAITING_ALLOW)
    other_panel = make_panel("other", PanelStatus.IDLE)

    tracker.panels["hwnd-important"] = important_panel
    tracker.panels["hwnd-other"] = other_panel

    # Fake window objects exposing only .Name.
    windows = [
        SimpleNamespace(Name="Dummy - important - Visual Studio Code"),
        SimpleNamespace(Name="Dummy - other - Visual Studio Code"),
    ]

    # After computing scores, the important repo should sort first.
    tracker.refresh_priority_scores()
    ordered = tracker.sort_windows_by_priority(windows)

    assert ordered[0].Name.startswith("Dummy - important")
    assert ordered[1].Name.startswith("Dummy - other")
