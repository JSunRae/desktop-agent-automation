from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from automation import panel_tracker
from automation.panel_task_dispatcher import TaskFeedEntry, TaskPanelDispatcher
from automation.panel_tracker import (
    PanelState,
    PanelStatus,
    check_for_task_completed,
    process_finished_panels_with_prompts,
)


class _DummyTrackerForDispatcher:
    def __init__(self) -> None:
        self.repo_prompt_indices: dict[str, int] = {}

    def get_repo_prompt_counter(self, repo_name: str | None) -> int:
        key = (repo_name or "__default__").lower()
        return self.repo_prompt_indices.get(key, 0)

    def advance_prompt_index(self, repo_name: str | None, *, steps: int = 1) -> None:
        if steps < 1:
            return
        key = (repo_name or "__default__").lower()
        current = self.repo_prompt_indices.get(key, 0)
        self.repo_prompt_indices[key] = current + steps


class _DummyMetrics:
    def record_response_feedback(self, *args, **kwargs):
        pass

    def record_model_selection(self, *args, **kwargs):
        pass

    def record_prompt_seeding(self, *args, **kwargs):
        pass

    def record_assignment(self, *args, **kwargs):
        pass

    def record_keep_new_chat_event(self, *args, **kwargs):
        pass

    def record_seeding_attempt(self, *args, **kwargs):
        pass


class _DummyCostTracker:
    def record_text_usage(self, *args, **kwargs):
        pass


def _prepare_panel_tracker_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(panel_tracker, "_tracker", None)
    monkeypatch.setattr(panel_tracker, "PANEL_STATE_PATH", tmp_path / "panel_state.json")
    monkeypatch.setattr(panel_tracker, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(panel_tracker, "ENABLE_SEND_TO_INACTIVE_PANELS", True)
    monkeypatch.setattr(panel_tracker, "FINISHED_PANEL_DRY_RUN", False)
    dummy_metrics = _DummyMetrics()
    monkeypatch.setattr(panel_tracker, "get_metrics_tracker", lambda: dummy_metrics)
    monkeypatch.setattr(panel_tracker, "get_cost_tracker", lambda: _DummyCostTracker())
    return dummy_metrics


def _build_finished_panel(title: str, panel_id: str) -> PanelState:
    now = datetime.now()
    panel = PanelState(
        window_title=title,
        panel_id=panel_id,
        first_seen=now - timedelta(minutes=60),
        last_allow_click=now - timedelta(minutes=40),
        last_output_change=now - timedelta(minutes=40),
    )
    panel.status = PanelStatus.FINISHED
    panel.last_output_sample = "All done and ready for next steps"
    return panel


def test_automation_task_ingestion_rotates_prompts(tmp_path):
    feed = tmp_path / "prompts.txt"
    feed.write_text(
        "1. Task A\nComplete the audit\n\n2. Task B\nShip the release notes\n\n3. Task C\nVerify panel state\n",
        encoding="utf-8",
    )

    dispatcher = TaskPanelDispatcher(prompt_path=feed)
    tracker = _DummyTrackerForDispatcher()

    first = dispatcher.reserve_task_for_panel(
        tracker=tracker,
        panel=None,
        panel_key="panel-1",
        repo_name=None,
    )
    second = dispatcher.reserve_task_for_panel(
        tracker=tracker,
        panel=None,
        panel_key="panel-2",
        repo_name=None,
    )

    assert first is not None and second is not None
    assert first.task_id != second.task_id
    assert dispatcher._active_assignments[first.task_id] == "panel-1"
    assert dispatcher._active_assignments[second.task_id] == "panel-2"

    dispatcher.release_task(first.task_id, "panel-1")
    assert first.task_id not in dispatcher._active_assignments


def test_automation_finished_panel_loop_seeds_prompt(monkeypatch, tmp_path):
    _prepare_panel_tracker_environment(tmp_path, monkeypatch)
    tracker = panel_tracker.get_tracker()

    panel = _build_finished_panel("RepoX - Copilot", "panel-42")
    panel_key = tracker.build_panel_key(panel)
    tracker.panels[panel_key] = panel

    dispatcher_entry = TaskFeedEntry(
        repo_key="default",
        repo_name="RepoX",
        prompt_index=0,
        prompt_text="Generate a review doc",
        prompt_preview="Generate a review doc",
        prompt_id="abc123",
        task_id="repox:abc123",
        model_label="GPT-5.1 Codex Mini",
        source_path=Path("tasks/generated_prompts/latest.txt"),
        batch_id="batch-1",
    )

    class _StubDispatcher:
        def __init__(self, entry: TaskFeedEntry) -> None:
            self.entry = entry
            self.tracked: list[list[str]] = []
            self.released: list[tuple[str, str]] = []

        def sync_active_assignments(self, tracker_arg) -> None:
            pass

        def track_idle_panels(self, panel_keys: list[str]) -> None:
            self.tracked.append(panel_keys)

        def reserve_task_for_panel(self, **kwargs) -> TaskFeedEntry | None:
            return self.entry

        def release_task(self, task_id: str, panel_key: str) -> None:
            self.released.append((task_id, panel_key))

    stub_dispatcher = _StubDispatcher(dispatcher_entry)
    monkeypatch.setattr(panel_tracker, "get_task_panel_dispatcher", lambda: stub_dispatcher)
    monkeypatch.setattr(panel_tracker, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(panel_tracker, "_try_click_keep_edits", lambda vs_win, panel_arg: (True, True))
    seed_calls: list[str] = []

    def _fake_seed(vs_win, prompt_text, panel_title, prompt_index, panel_id):
        seed_calls.append(prompt_text)
        return True

    monkeypatch.setattr(panel_tracker, "_seed_prompt_in_window", _fake_seed)

    vs_win = SimpleNamespace(Name=panel.window_title)
    processed = process_finished_panels_with_prompts([vs_win])

    assert processed == 1
    assert panel.seeded_prompt is True
    assert panel.assigned_task_id == dispatcher_entry.task_id
    assert panel.status == PanelStatus.RUNNING
    assert seed_calls and seed_calls[0] == dispatcher_entry.prompt_text


def test_automation_completion_review_marks_completed(monkeypatch, tmp_path):
    _prepare_panel_tracker_environment(tmp_path, monkeypatch)
    tracker = panel_tracker.get_tracker()

    panel = _build_finished_panel("RepoY - Copilot", "")
    key = tracker.build_panel_key(panel)
    tracker.panels[key] = panel

    monkeypatch.setattr(panel_tracker, "get_panel_output_text", lambda vs_win, max_depth=60: "Task completed successfully")
    vs_win = SimpleNamespace(Name=panel.window_title)

    assert check_for_task_completed(vs_win) is True
    assert panel.status == PanelStatus.COMPLETED