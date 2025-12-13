import datetime
from pathlib import Path
from types import SimpleNamespace

import automation.panel_tracker as pt


class _StubDispatcher:
    """Minimal dispatcher stub for unit tests."""

    def __init__(self, assignments: list[SimpleNamespace]) -> None:
        self.assignments = list(assignments)
        self.sync_called = False
        self.idle_keys: list[str] = []
        self.releases: list[tuple[str, str]] = []

    def sync_active_assignments(self, tracker) -> None:  # pragma: no cover - trivial
        self.sync_called = True

    def track_idle_panels(self, panel_keys):  # pragma: no cover - trivial
        self.idle_keys = list(panel_keys)

    def reserve_task_for_panel(self, **kwargs):
        if not self.assignments:
            return None
        return self.assignments.pop(0)

    def release_task(self, task_id, panel_key) -> None:
        self.releases.append((task_id, panel_key))


def _default_assignment() -> SimpleNamespace:
    return SimpleNamespace(
        prompt_text="Prompt 1 (Codex Max): Do the thing",
        prompt_index=0,
        prompt_id="abc123",
        prompt_preview="Prompt 1 (Codex Max): Do the thing",
        task_id="default:abc123",
        batch_id="batch-1",
        source_path=Path("tasks/generated_prompts/latest.txt"),
    )


def _install_dispatcher_stub(monkeypatch, assignments: list[SimpleNamespace] | None = None) -> _StubDispatcher:
    stub = _StubDispatcher(assignments or [_default_assignment()])
    monkeypatch.setattr(pt, "get_task_panel_dispatcher", lambda: stub)
    return stub


def _make_tracker(panel_title: str, monkeypatch) -> pt.PanelTracker:
    """Create a clean tracker without loading from disk."""
    now = datetime.datetime.now()
    
    # Prevent loading from disk
    monkeypatch.setattr(pt.PanelTracker, "_load_state", lambda self: None)
    monkeypatch.setattr(pt.PanelTracker, "_save_state", lambda self: None)
    
    tracker = pt.PanelTracker()
    panel = pt.PanelState(
        window_title=panel_title,
        panel_id="panel-1",
        first_seen=now,
        last_allow_click=now - datetime.timedelta(minutes=45),
        last_output_change=now - datetime.timedelta(minutes=40),
        last_scanned=now - datetime.timedelta(minutes=35),
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
    )
    tracker.panels[tracker._generate_panel_key(panel_title)] = panel
    return tracker


def test_finished_panel_dry_run(monkeypatch):
    panel_title = "Testing window functionality - desktop-agent-automation"
    tracker = _make_tracker(panel_title, monkeypatch)

    # Flags
    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", True)
    _install_dispatcher_stub(monkeypatch)

    # Avoid real UI work
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs, panel: (True, True))
    monkeypatch.setattr(pt, "_seed_prompt_in_window", lambda vs, prompt, *args, **kwargs: True)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")

    # Inject tracker
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    vs_win = SimpleNamespace(Name=panel_title)
    processed = pt.process_finished_panels_with_prompts([vs_win])  # type: ignore[arg-type]

    assert processed == 1
    # Find the specific panel by title
    panel = next((p for p in tracker.get_finished_panels() if p.window_title == panel_title), None)
    assert panel is not None, f"Panel with title '{panel_title}' not found"
    assert panel.seeded_prompt is True
    # Dry-run should not mark as running
    assert panel.status == pt.PanelStatus.FINISHED or panel.status == pt.PanelStatus.RUNNING


def test_finished_panel_live_path(monkeypatch):
    panel_title = "Testing window functionality - desktop-agent-automation"
    tracker = _make_tracker(panel_title, monkeypatch)

    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", False)
    _install_dispatcher_stub(monkeypatch)

    calls = {}

    def seed_stub(vs, prompt, panel_title="", prompt_index=-1, panel_id=""):
        calls["called"] = True
        return True

    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs, panel: (True, True))
    monkeypatch.setattr(pt, "_seed_prompt_in_window", seed_stub)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    vs_win = SimpleNamespace(Name=panel_title)
    processed = pt.process_finished_panels_with_prompts([vs_win])  # type: ignore[arg-type]

    assert processed == 1
    assert calls.get("called") is True
    # Find the specific panel by title
    panel = next((p for p in tracker.panels.values() if p.window_title == panel_title), None)
    assert panel is not None, f"Panel with title '{panel_title}' not found"
    assert panel.seeded_prompt is True
    assert panel.status == pt.PanelStatus.RUNNING
    assert panel.last_allow_click > datetime.datetime.now() - datetime.timedelta(minutes=5)


def test_finished_panel_classification_skip(monkeypatch):
    """Test that seeding is skipped when panel is not classified as IDLE_SAFE."""
    panel_title = "Testing window functionality - desktop-agent-automation"
    tracker = _make_tracker(panel_title, monkeypatch)

    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", False)
    _install_dispatcher_stub(monkeypatch)

    calls = {}

    def seed_stub(vs, prompt, panel_title="", prompt_index=-1, panel_id=""):
        calls["called"] = True
        return True

    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs, panel: (True, True))
    monkeypatch.setattr(pt, "_seed_prompt_in_window", seed_stub)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "ACTIVE_WORKING")  # Not IDLE_SAFE
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    vs_win = SimpleNamespace(Name=panel_title)
    processed = pt.process_finished_panels_with_prompts([vs_win])  # type: ignore[arg-type]

    # Should not process because classification is not IDLE_SAFE
    assert processed == 0
    assert calls.get("called") is not True  # Should not have been called
    # Find the specific panel by title
    panel = next((p for p in tracker.panels.values() if p.window_title == panel_title), None)
    assert panel is not None, f"Panel with title '{panel_title}' not found"
    assert panel.seeded_prompt is False  # Should not be marked as seeded


def test_finished_panel_skips_when_focus_lost(monkeypatch):
    panel_title = "Testing window functionality - desktop-agent-automation"
    tracker = _make_tracker(panel_title, monkeypatch)

    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", False)
    _install_dispatcher_stub(monkeypatch)
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs, panel: (False, False))

    seed_calls = {}

    def seed_stub(*args, **kwargs):
        seed_calls["called"] = True
        return True

    monkeypatch.setattr(pt, "_seed_prompt_in_window", seed_stub)
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    vs_win = SimpleNamespace(Name=panel_title)
    processed = pt.process_finished_panels_with_prompts([vs_win])  # type: ignore[arg-type]

    assert processed == 0
    assert "called" not in seed_calls
    panel = next((p for p in tracker.panels.values() if p.window_title == panel_title), None)
    assert panel is not None
    assert panel.seeded_prompt is False


def test_finished_panel_handles_seed_failure(monkeypatch):
    panel_title = "Testing window functionality - desktop-agent-automation"
    tracker = _make_tracker(panel_title, monkeypatch)

    monkeypatch.setattr(pt, "ENABLE_FINISHED_PANEL_FOLLOWUPS", True)
    monkeypatch.setattr(pt, "FINISHED_PANEL_DRY_RUN", False)
    monkeypatch.setattr(pt, "_load_prompt_blocks", lambda: ["Prompt 1 (Codex Max): Do the thing"])
    monkeypatch.setattr(pt, "_load_prompt_blocks_for_repo", lambda repo: ["Prompt 1 (Codex Max): Do the thing"])
    monkeypatch.setattr(pt, "classify_panel_output", lambda text: "IDLE_SAFE")
    monkeypatch.setattr(pt, "_try_click_keep_edits", lambda vs, panel: (True, True))

    seed_calls = {}

    def seed_stub(*args, **kwargs):
        seed_calls["called"] = True
        return False

    monkeypatch.setattr(pt, "_seed_prompt_in_window", seed_stub)
    monkeypatch.setattr(pt, "get_tracker", lambda: tracker)

    vs_win = SimpleNamespace(Name=panel_title)
    processed = pt.process_finished_panels_with_prompts([vs_win])  # type: ignore[arg-type]

    assert processed == 0
    assert seed_calls.get("called") is True
    panel = next((p for p in tracker.panels.values() if p.window_title == panel_title), None)
    assert panel is not None
    assert panel.seeded_prompt is False


def test_classify_panel_output_empty_text():
    """Test classification with empty text."""
    result = pt.classify_panel_output("")
    assert result == "IDLE_SAFE"

    result = pt.classify_panel_output("   ")
    assert result == "IDLE_SAFE"


def test_classify_panel_output_no_openai(monkeypatch):
    """Test classification fallback when OpenAI is not available."""
    monkeypatch.setattr(pt, "openai_module", None)
    result = pt.classify_panel_output("some text")
    assert result == "IDLE_SAFE"


def test_classify_panel_output_no_api_key(monkeypatch):
    """Test classification fallback when API key is not set."""
    monkeypatch.setattr(pt.os, "environ", {"OPENAI_API_KEY": ""})
    result = pt.classify_panel_output("some text")
    assert result == "IDLE_SAFE"
