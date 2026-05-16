from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


_TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="desktop-agent-automation-tests-"))

os.environ.setdefault(
    "AUTOMATION_METRICS_PATH",
    str(_TEST_RUNTIME_ROOT / "automation" / "metrics.json"),
)
os.environ.setdefault(
    "AUTOMATION_ASSIGNMENT_METRICS_PATH",
    str(_TEST_RUNTIME_ROOT / "automation" / "assignment_metrics.jsonl"),
)
os.environ.setdefault(
    "CROSS_REPO_TODO_CACHE_PATH",
    str(_TEST_RUNTIME_ROOT / "automation" / "cross_repo_todo_cache.json"),
)
os.environ.setdefault(
    "NORTH_STAR_CACHE_PATH",
    str(_TEST_RUNTIME_ROOT / "state" / "north_star_cache.json"),
)
os.environ.setdefault(
    "WORKSTREAM_COORDINATION_STATE_PATH",
    str(_TEST_RUNTIME_ROOT / "state" / "workstream_coordination.json"),
)
os.environ.setdefault(
    "ALLOW_METRICS_LOG_PATH",
    str(_TEST_RUNTIME_ROOT / "automation" / "allow_metrics.jsonl"),
)
os.environ.setdefault(
    "ALLOW_EVENTS_PERSIST_PATH",
    str(_TEST_RUNTIME_ROOT / "automation" / "allow_events.json"),
)


def _reset_runtime_singletons() -> None:
    from automation import metrics, north_star, workstream_coordination
    from automation.feedback_analyzer import get_feedback_analyzer

    metrics._tracker_instance = None
    workstream_coordination._WORKSTREAM_COORDINATOR = None
    north_star._cached_context = None
    north_star._cache_loaded_at = None
    if hasattr(get_feedback_analyzer, "_instance"):
        delattr(get_feedback_analyzer, "_instance")


@pytest.fixture(autouse=True)
def isolate_runtime_state() -> None:
    _reset_runtime_singletons()
    yield
    _reset_runtime_singletons()
