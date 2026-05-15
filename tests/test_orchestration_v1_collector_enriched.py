from __future__ import annotations

import json
from pathlib import Path

from automation.cross_repo_todo_ingestion import CrossRepoTodoSnapshot, TodoItem
from automation.north_star import ActiveTask
from automation.orchestration_v1 import collector
from automation.orchestration_v1.models import (
    ManagedRepoConfig,
    RepoDependencyRules,
    RepoSafetyRules,
    Severity,
    WorkStatus,
)


class _EmptyTodoAnalysis:
    def tasks_for_repo(self, repo_name: str):
        return []


class _EmptyTodoService:
    def analyze_dependencies(self):
        return _EmptyTodoAnalysis()

    def get_snapshot(self):
        return CrossRepoTodoSnapshot(version=1, generated_at="2026-04-25T00:00:00Z", repos=[])


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo_config(tmp_path: Path, *, repo_id: str = "Trading") -> ManagedRepoConfig:
    repo_root = tmp_path / repo_id
    repo_root.mkdir(parents=True, exist_ok=True)
    return ManagedRepoConfig(
        repo_id=repo_id,
        root_path=str(repo_root),
        purpose="collector enrichment test repo",
        instruction_files=[],
        task_sources=[],
        handover_locations=[],
        report_locations=[],
        validation_commands=["pytest -q"],
        safety_rules=RepoSafetyRules(),
        dependencies=RepoDependencyRules(),
    )


def test_from_agent_assignment_maps_priorities() -> None:
    p0 = collector.from_agent_assignment(
        ActiveTask(
            task_id="TASK-P0",
            title="Unblock release",
            description="Critical ship blocker",
            status="planned",
            priority="P0",
            repo="Trading",
        ),
        "Trading",
    )
    p1 = collector.from_agent_assignment(
        ActiveTask(
            task_id="TASK-P1",
            title="Fix regression",
            description="High-priority defect",
            status="planned",
            priority="P1",
            repo="Trading",
        ),
        "Trading",
    )
    p2 = collector.from_agent_assignment(
        ActiveTask(
            task_id="TASK-P2",
            title="Refresh docs",
            description="Routine follow-up",
            status="planned",
            priority="P2",
            repo="Trading",
        ),
        "Trading",
    )

    assert p0.severity == Severity.BLOCKER
    assert p1.severity == Severity.HIGH
    assert p2.severity == Severity.MEDIUM


def test_from_todo_item_handles_blocked_items() -> None:
    item = collector.from_todo_item(
        TodoItem(
            text="blocked by contracts schema promotion",
            title="Finish TF promotion follow-up",
            priority="P1",
            is_blocked=True,
            blocked_by=["contracts schema promotion"],
            section="Blocked",
        ),
        "TF",
    )

    assert item.status == WorkStatus.BLOCKED
    assert item.dependencies == ["contracts schema promotion"]
    assert item.metadata.get("source_kind") == "cross_repo_todo"


def test_collect_repo_context_falls_back_when_agent_assignments_absent(tmp_path: Path, monkeypatch) -> None:
    repo = _repo_config(tmp_path, repo_id="Trading")
    missing_ledger = tmp_path / "Trading" / "agent_assignments.json"

    monkeypatch.setattr(collector, "get_cross_repo_todo_service", lambda: _EmptyTodoService())
    monkeypatch.setattr(collector.north_star, "REPO_ASSIGNMENT_LEDGERS", {"Trading": missing_ledger})

    bundle = collector.collect_repo_context(repo)

    assignment_diag = bundle.source_diagnostics["agent_assignment"]
    assert assignment_diag["missing"] is True
    assert assignment_diag["extracted_candidate_count"] == 0
    assert bundle.prebuilt_work_items == []
    assert any("agent assignment source missing" in warning for warning in bundle.warnings)


def test_collect_repo_context_maps_in_progress_assignment_to_running(tmp_path: Path, monkeypatch) -> None:
    repo = _repo_config(tmp_path, repo_id="Trading")
    ledger_path = tmp_path / "Trading" / "agent_assignments.json"
    _write(
        ledger_path,
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "runtime-follow-through",
                        "title": "Wire orchestration discovery",
                        "description": "Consume assignments in orchestration_v1",
                        "status": "in_progress",
                        "priority": "P1",
                    }
                ]
            },
            indent=2,
        ),
    )

    monkeypatch.setattr(collector, "get_cross_repo_todo_service", lambda: _EmptyTodoService())
    monkeypatch.setattr(collector.north_star, "REPO_ASSIGNMENT_LEDGERS", {"Trading": ledger_path})

    bundle = collector.collect_repo_context(repo)

    assert len(bundle.prebuilt_work_items) == 1
    item = bundle.prebuilt_work_items[0]
    assert item.status == WorkStatus.RUNNING
    assert item.severity == Severity.HIGH
    assert item.metadata.get("source_kind") == "agent_assignment"