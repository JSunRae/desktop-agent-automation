"""
Test round-robin prompt assignment backed by dispatcher feeds.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import automation.panel_tracker as pt
from automation import panel_task_dispatcher as dispatcher


def _make_tracker_with_multiple_panels(monkeypatch):
    """Create a tracker with multiple finished panels."""
    now = dt.datetime.now()

    # Prevent loading from disk
    monkeypatch.setattr(pt.PanelTracker, "_load_state", lambda self: None)
    monkeypatch.setattr(pt.PanelTracker, "_save_state", lambda self: None)

    tracker = pt.PanelTracker()

    # Create 3 finished panels
    for i in range(1, 4):
        panel_title = f"Test Panel {i} - desktop-agent-automation"
        panel = pt.PanelState(
            window_title=panel_title,
            panel_id=f"panel-{i}",
            first_seen=now,
            last_allow_click=now - dt.timedelta(minutes=45),
            last_output_change=now - dt.timedelta(minutes=40),
            last_scanned=now - dt.timedelta(minutes=35),
            last_output_sample="next steps pending",
            last_output_hash=f"hash{i}",
            status=pt.PanelStatus.FINISHED,
            is_running=False,
            idle_reason=pt.IdleReason.POSSIBLY_FINISHED,
            sent_completion_check=True,
            sent_next_steps_response=True,
            sent_please_continue=False,
            times_checked=1,
            seeded_prompt=False,
        )
        tracker.panels[tracker._generate_panel_key(panel_title)] = panel

    return tracker


def test_round_robin_prompt_assignment(monkeypatch):
    """Test that prompts are assigned in round-robin fashion."""
    tracker = _make_tracker_with_multiple_panels(monkeypatch)

    # Flags
    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", True)

    # Create 4 different prompts
    prompts = [
        "Prompt 1 (Codex Max): Task A",
        "Prompt 2 (Codex): Task B",
        "Prompt 3 (Codex Mini): Task C",
        "Prompt 4 (Grok): Task D",
    ]
    monkeypatch.setattr(pt, "_load_prompt_blocks_for_repo", lambda repo=None: prompts)

    # Avoid real UI work
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs, panel: (True, True))
    monkeypatch.setattr(pt, "_seed_prompt_in_window", lambda vs, prompt, *args, **kwargs: True)

    # Inject tracker
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    # Create window controls for all panels
    vs_windows = [
        SimpleNamespace(Name=f"Test Panel {i} - desktop-agent-automation")
        for i in range(1, 4)
    ]

    # Process panels
    processed = pt.process_finished_panels_with_prompts(vs_windows)  # type: ignore[arg-type]

    assert processed == 3, f"Expected 3 panels processed, got {processed}"

    # Verify round-robin assignment
    panel_1 = next((p for p in tracker.panels.values() if "Test Panel 1" in p.window_title), None)
    panel_2 = next((p for p in tracker.panels.values() if "Test Panel 2" in p.window_title), None)
    panel_3 = next((p for p in tracker.panels.values() if "Test Panel 3" in p.window_title), None)

    assert panel_1 is not None
    assert panel_2 is not None
    assert panel_3 is not None

    # Each panel should get a different prompt
    assert panel_1.assigned_prompt_index == 0, f"Panel 1 should get prompt 0, got {panel_1.assigned_prompt_index}"
    assert panel_2.assigned_prompt_index == 1, f"Panel 2 should get prompt 1, got {panel_2.assigned_prompt_index}"
    assert panel_3.assigned_prompt_index == 2, f"Panel 3 should get prompt 2, got {panel_3.assigned_prompt_index}"

    # Next prompt index should be 3
    assert tracker.next_prompt_index == 3, f"Next prompt index should be 3, got {tracker.next_prompt_index}"


class _FakeVSWindow(SimpleNamespace):
    """Simple stand-in for a VS Code window control."""

    def __init__(self, name: str) -> None:
        super().__init__(Name=name)


def _make_tracker(monkeypatch) -> pt.PanelTracker:
    monkeypatch.setattr(pt.PanelTracker, "_load_state", lambda self: None)
    monkeypatch.setattr(pt.PanelTracker, "_save_state", lambda self: None)
    return pt.PanelTracker()


def _make_panel(title: str, repo_name: str | None) -> pt.PanelState:
    now = dt.datetime.now()
    return pt.PanelState(
        window_title=title,
        panel_id=title.lower().replace(" ", "-"),
        first_seen=now,
        last_allow_click=now - dt.timedelta(minutes=40),
        last_output_change=now - dt.timedelta(minutes=35),
        last_scanned=now - dt.timedelta(minutes=30),
        last_output_sample="next steps pending",
        last_output_hash="hash",
        status=pt.PanelStatus.FINISHED,
        is_running=False,
        idle_reason=pt.IdleReason.POSSIBLY_FINISHED,
        sent_completion_check=True,
        sent_next_steps_response=True,
        repo_name=repo_name,
    )


def _write_feed(path: Path, prompts: list[str]) -> None:
    text = "\n\n".join(prompts) + "\n"
    path.write_text(text, encoding="utf-8")


def test_dispatcher_assigns_unique_tasks_across_repos(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch)

    panels = [
        _make_panel("Panel RepoOne A - RepoOne", "RepoOne"),
        _make_panel("Panel RepoOne B - RepoOne", "RepoOne"),
        _make_panel("Panel RepoTwo - RepoTwo", "RepoTwo"),
    ]
    for panel in panels:
        tracker.panels[tracker._generate_panel_key(panel.window_title)] = panel
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    feed_root = tmp_path / "generated_prompts"
    feed_root.mkdir()
    default_file = feed_root / "latest.txt"
    _write_feed(default_file, ["Prompt 1 (Codex): Default"])
    repo_one_dir = feed_root / "RepoOne"
    repo_one_dir.mkdir()
    _write_feed(
        repo_one_dir / "latest.txt",
        [
            "Prompt 1 (Codex): RepoOne Task Alpha",
            "Prompt 2 (Codex): RepoOne Task Beta",
        ],
    )
    repo_two_dir = feed_root / "RepoTwo"
    repo_two_dir.mkdir()
    _write_feed(
        repo_two_dir / "latest.txt",
        ["Prompt 1 (Codex): RepoTwo Task"],
    )

    task_dispatcher = dispatcher.TaskPanelDispatcher(prompt_path=default_file)
    monkeypatch.setattr(pt, "get_task_panel_dispatcher", lambda: task_dispatcher)

    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", True)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs_win, panel: (True, True))

    vs_windows = [_FakeVSWindow(panel.window_title) for panel in panels]

    processed = pt.process_finished_panels_with_prompts(vs_windows)  # type: ignore[arg-type]

    assert processed == 3
    assigned_ids = {panel.assigned_task_id for panel in panels}
    assert len(assigned_ids) == 3, "Each panel should receive a unique task"
    assert all(panel.seeded_prompt for panel in panels)
    assert panels[0].assigned_task_id.startswith("repoone:")
    assert panels[1].assigned_task_id.startswith("repoone:")
    assert panels[2].assigned_task_id.startswith("repotwo:")


def test_dispatcher_skips_when_feed_exhausted(monkeypatch, tmp_path):
    tracker = _make_tracker(monkeypatch)

    panels = [
        _make_panel("Panel RepoShort A - RepoShort", "RepoShort"),
        _make_panel("Panel RepoShort B - RepoShort", "RepoShort"),
    ]
    for panel in panels:
        tracker.panels[tracker._generate_panel_key(panel.window_title)] = panel
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    feed_root = tmp_path / "generated_prompts"
    feed_root.mkdir()
    default_file = feed_root / "latest.txt"
    _write_feed(default_file, [])
    repo_short = feed_root / "RepoShort"
    repo_short.mkdir()
    _write_feed(repo_short / "latest.txt", ["Prompt 1 (Codex): Only Task"])

    task_dispatcher = dispatcher.TaskPanelDispatcher(prompt_path=default_file)
    monkeypatch.setattr(pt, "get_task_panel_dispatcher", lambda: task_dispatcher)

    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", True)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs_win, panel: (True, True))

    vs_windows = [_FakeVSWindow(panel.window_title) for panel in panels]
    processed = pt.process_finished_panels_with_prompts(vs_windows)  # type: ignore[arg-type]

    assert processed == 1, "Only one panel should receive a task when feed has a single prompt"
    seeded_panels = [panel for panel in panels if panel.seeded_prompt]
    assert len(seeded_panels) == 1
    assert seeded_panels[0].assigned_task_id.startswith("reposhort:")
