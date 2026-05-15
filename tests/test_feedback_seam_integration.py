from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from types import SimpleNamespace

import automation.panel_seeding as panel_seeding
import automation.panel_tracker as pt
import automation.task_discovery_daemon as daemon_module
from automation.panel_task_dispatcher import TaskPanelDispatcher
from automation.task_discovery_daemon import TaskDiscoveryDaemon


class _TrackerStub:
    def __init__(self) -> None:
        self.advance_calls: list[tuple[str | None, int]] = []

    def advance_prompt_index(self, repo_name: str | None, *, steps: int = 1) -> None:
        self.advance_calls.append((repo_name, steps))


def _write_feed(path: Path, prompts: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n\n".join(prompts)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _make_tracker(monkeypatch, panel_title: str, repo_name: str) -> tuple[pt.PanelTracker, pt.PanelState]:
    now = dt.datetime.now()
    monkeypatch.setattr(pt.PanelTracker, "_load_state", lambda self: None)
    monkeypatch.setattr(pt.PanelTracker, "_save_state", lambda self: None)

    tracker = pt.PanelTracker()
    panel = pt.PanelState(
        window_title=panel_title,
        panel_id="panel-1",
        first_seen=now,
        last_allow_click=now - dt.timedelta(minutes=45),
        last_output_change=now - dt.timedelta(minutes=40),
        last_scanned=now - dt.timedelta(minutes=35),
        last_output_sample="next steps pending",
        last_output_hash="hash",
        status=pt.PanelStatus.FINISHED,
        is_running=False,
        idle_reason=pt.IdleReason.POSSIBLY_FINISHED,
        sent_completion_check=True,
        sent_next_steps_response=True,
        sent_please_continue=False,
        times_checked=1,
        seeded_prompt=False,
        repo_name=repo_name,
    )
    tracker.panels[tracker._generate_panel_key(panel_title)] = panel
    return tracker, panel


def test_dispatcher_fires_empty_callback_when_all_feeds_empty(tmp_path):
    feed_root = tmp_path / "generated_prompts"
    default_feed = feed_root / "latest.txt"
    repo_feed = feed_root / "RepoEmpty" / "latest.txt"
    _write_feed(default_feed, [])
    _write_feed(repo_feed, [])

    dispatcher = TaskPanelDispatcher(prompt_path=default_feed, allow_default_fallback=False)
    tracker = _TrackerStub()
    fired = threading.Event()
    dispatcher.register_feed_empty_callback(fired.set)

    entry = dispatcher.next_entry(
        tracker=tracker,
        panel_key="panel-1",
        repo_name="RepoEmpty",
    )

    assert entry is None
    assert fired.wait(1), "Expected dispatcher empty-feed callback to fire"


def test_trigger_immediate_refresh_skips_sleep_and_calls_refresh(monkeypatch):
    first_iteration = threading.Event()
    refresh_called = threading.Event()

    dispatcher = SimpleNamespace(
        register_feed_empty_callback=lambda callback: None,
        get_low_task_repos=lambda repo_names=None, threshold=0: [],
        reset_cache=lambda: None,
    )
    todo_service = SimpleNamespace(refresh=lambda: None)

    class _OrchestratorStub:
        def refresh_repo_configs(self):
            first_iteration.set()
            return [SimpleNamespace(name="RepoOne")]

        def refresh_all_feeds(self):
            refresh_called.set()
            return []

    monkeypatch.setattr(daemon_module, "get_task_panel_dispatcher", lambda: dispatcher)
    monkeypatch.setattr(daemon_module, "get_cross_repo_todo_service", lambda: todo_service)
    monkeypatch.setattr(daemon_module, "CROSS_REPO_TODO_ENABLED", False)

    daemon = TaskDiscoveryDaemon(
        interval_seconds=3600,
        low_task_threshold=1,
        orchestrator=_OrchestratorStub(),
    )

    try:
        daemon.start()
        assert first_iteration.wait(1), "Expected daemon to complete its initial iteration"

        daemon.trigger_immediate_refresh()

        assert refresh_called.wait(1), "Expected immediate refresh request to wake the daemon"
    finally:
        daemon.stop()


def test_finished_panel_empty_feed_refreshes_and_seeds(monkeypatch, tmp_path):
    panel_title = "RepoChain panel - RepoChain"
    tracker, panel = _make_tracker(monkeypatch, panel_title, "RepoChain")

    feed_root = tmp_path / "generated_prompts"
    default_feed = feed_root / "latest.txt"
    repo_feed = feed_root / "RepoChain" / "latest.txt"
    _write_feed(default_feed, [])
    _write_feed(repo_feed, [])

    dispatcher = TaskPanelDispatcher(prompt_path=default_feed, allow_default_fallback=False)
    refresh_complete = threading.Event()
    todo_service = SimpleNamespace(refresh=lambda: None)

    class _OrchestratorStub:
        def refresh_repo_configs(self):
            return [SimpleNamespace(name="RepoChain")]

        def refresh_all_feeds(self):
            _write_feed(repo_feed, ["Prompt 1 (Codex): Fresh follow-up task"])
            refresh_complete.set()
            return [SimpleNamespace(prompt_count=1)]

    monkeypatch.setattr(daemon_module, "get_task_panel_dispatcher", lambda: dispatcher)
    monkeypatch.setattr(daemon_module, "get_cross_repo_todo_service", lambda: todo_service)
    monkeypatch.setattr(daemon_module, "CROSS_REPO_TODO_ENABLED", False)

    daemon = TaskDiscoveryDaemon(
        interval_seconds=3600,
        low_task_threshold=0,
        orchestrator=_OrchestratorStub(),
    )

    trigger_calls = {"count": 0}
    real_trigger = daemon.trigger_immediate_refresh

    def counted_trigger() -> None:
        trigger_calls["count"] += 1
        real_trigger()

    daemon.trigger_immediate_refresh = counted_trigger  # type: ignore[assignment]

    monkeypatch.setattr(panel_seeding, "ENABLE_ON_DEMAND_FEED_REFRESH", True)
    monkeypatch.setattr(panel_seeding.task_discovery_daemon, "trigger_immediate_refresh", counted_trigger)
    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", True)
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)
    monkeypatch.setattr(pt, "get_task_panel_dispatcher", lambda: dispatcher)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs_win, current_panel: (True, True))
    monkeypatch.setattr(pt, "_seed_prompt_in_window", lambda *args, **kwargs: True)
    monkeypatch.setattr(pt, "_load_prompt_blocks_for_repo", lambda repo=None: [])

    try:
        daemon.start()

        first_processed = pt.process_finished_panels_with_prompts([SimpleNamespace(Name=panel_title)])
        assert first_processed == 0
        assert refresh_complete.wait(1), "Expected empty-feed seeding path to trigger a refresh"

        second_processed = pt.process_finished_panels_with_prompts([SimpleNamespace(Name=panel_title)])

        assert second_processed == 1
        assert trigger_calls["count"] >= 1
        assert panel.seeded_prompt is True
        assert panel.assigned_task_id is not None
    finally:
        daemon.stop()