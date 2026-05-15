from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from automation.orchestration_v1 import collector
from automation.orchestration_v1.loop import OrchestrationV1Loop
from automation.orchestration_v1.registry import load_registry


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _CollectorTodoAnalysis:
    def tasks_for_repo(self, repo_name: str):
        if repo_name != "alpha":
            return []
        return [
            SimpleNamespace(
                title="Blocked collector follow-up",
                priority="P1",
                is_blocked=True,
                blocked_by=["shared-fixtures"],
            )
        ]


class _CollectorTodoService:
    def analyze_dependencies(self):
        return _CollectorTodoAnalysis()

    def get_snapshot(self):
        return SimpleNamespace(
            repos=[
                SimpleNamespace(
                    repo_name="alpha",
                    todo_paths=["alpha/Todo.md"],
                )
            ]
        )


def test_orchestration_v1_ingests_structured_task_json(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "agent_assignments.json",
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "copilot-usage-monitor",
                        "title": "Copilot Usage Monitor",
                        "description": "Wire the recurring runtime poller into the automation loop.",
                        "status": "in_progress",
                    },
                    {
                        "id": "closed-task",
                        "title": "Closed Task",
                        "status": "completed",
                    },
                ]
            },
            indent=2,
        ),
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "structured-task-test",
        "description": "structured json task ingestion",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": [],
                "task_sources": ["agent_assignments.json"],
                "handover_locations": [],
                "report_locations": [],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": [],
                    "protected_signal_files": [],
                    "allow_paths": ["alpha/**"],
                    "requires_explicit_approval_for": [],
                },
                "dependencies": {
                    "blocked_by": [],
                    "follow_up_targets": [],
                    "source_of_truth_for": [],
                },
            }
        ],
    }

    registry_path = tmp_path / "registry.json"
    _write(registry_path, json.dumps(registry_payload, indent=2))

    loop = OrchestrationV1Loop(
        registry=load_registry(registry_path),
        ledger_path=ledger_path,
        dispatch_root=dispatch_root,
        report_root=report_root,
    )

    result = loop.run_once(poll_seconds=0, poll_interval_seconds=1)

    assert result.selected_work_item is not None
    assert "copilot usage monitor" in result.selected_work_item.title.lower()
    assert "closed task" not in result.selected_work_item.title.lower()


def test_orchestration_v1_reports_source_mismatch_diagnostics(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"
    repo_root.mkdir(parents=True, exist_ok=True)

    registry_payload = {
        "version": 1,
        "workspace_id": "discovery-diagnostics-test",
        "description": "missing source diagnostics",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": ["README.md"],
                "task_sources": ["Todo.md", "docs/Todo.md"],
                "handover_locations": ["HANDOVER.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": [],
                    "protected_signal_files": [],
                    "allow_paths": ["alpha/**"],
                    "requires_explicit_approval_for": [],
                },
                "dependencies": {
                    "blocked_by": [],
                    "follow_up_targets": [],
                    "source_of_truth_for": [],
                },
            }
        ],
    }

    registry_path = tmp_path / "registry.json"
    _write(registry_path, json.dumps(registry_payload, indent=2))

    loop = OrchestrationV1Loop(
        registry=load_registry(registry_path),
        ledger_path=ledger_path,
        dispatch_root=dispatch_root,
        report_root=report_root,
    )

    result = loop.run_once(poll_seconds=0, poll_interval_seconds=1)

    assert result.selected_work_item is None
    assert result.decision is not None
    assert "source mismatch summary" in result.decision.reason
    repo_diag = result.diagnostics["discovery"]["repos"]["alpha"]
    assert repo_diag["sources"]["task"]["matched_files"] == []
    assert repo_diag["sources"]["task"]["unmatched_entries"] == ["Todo.md", "docs/Todo.md"]
    assert repo_diag["sources"]["handover"]["matched_files"] == []


def test_orchestration_v1_reports_empty_structured_source_candidates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "This file has prose only.\n\nNo markdown bullets are present here.\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "empty-candidate-diagnostics-test",
        "description": "empty candidate diagnostics",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": [],
                "task_sources": ["Todo.md"],
                "handover_locations": [],
                "report_locations": [],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": [],
                    "protected_signal_files": [],
                    "allow_paths": ["alpha/**"],
                    "requires_explicit_approval_for": [],
                },
                "dependencies": {
                    "blocked_by": [],
                    "follow_up_targets": [],
                    "source_of_truth_for": [],
                },
            }
        ],
    }

    registry_path = tmp_path / "registry.json"
    _write(registry_path, json.dumps(registry_payload, indent=2))

    loop = OrchestrationV1Loop(
        registry=load_registry(registry_path),
        ledger_path=ledger_path,
        dispatch_root=dispatch_root,
        report_root=report_root,
    )

    result = loop.run_once(poll_seconds=0, poll_interval_seconds=1)

    assert result.selected_work_item is None
    assert result.decision is not None
    assert "found structured files but extracted no task candidates" in result.decision.reason
    assert any("Todo.md" in note for note in result.notes)

    repo_diag = result.diagnostics["discovery"]["repos"]["alpha"]
    task_diag = repo_diag["sources"]["task"]
    expected_matched_path = str((repo_root / "Todo.md")).replace("\\", "/")
    assert task_diag["matched_files"] == [expected_matched_path]
    assert task_diag["extracted_candidate_count"] == 0
    assert task_diag["files_with_no_candidates"] == ["Todo.md"]
    assert task_diag["files_with_zero_items"] == ["Todo.md"]


def test_orchestration_v1_reports_collector_enriched_status_rejections_in_discovery_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "agent_assignments.json",
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

    monkeypatch.setattr(collector, "get_cross_repo_todo_service", lambda: _CollectorTodoService())
    monkeypatch.setattr(
        collector.north_star,
        "REPO_ASSIGNMENT_LEDGERS",
        {"alpha": repo_root / "agent_assignments.json"},
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "collector-enriched-status-rejections-test",
        "description": "collector-enriched no-eligible diagnostics",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": [],
                "task_sources": [],
                "handover_locations": [],
                "report_locations": [],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": [],
                    "protected_signal_files": [],
                    "allow_paths": ["alpha/**"],
                    "requires_explicit_approval_for": [],
                },
                "dependencies": {
                    "blocked_by": [],
                    "follow_up_targets": [],
                    "source_of_truth_for": [],
                },
            }
        ],
    }

    registry_path = tmp_path / "registry.json"
    _write(registry_path, json.dumps(registry_payload, indent=2))

    loop = OrchestrationV1Loop(
        registry=load_registry(registry_path),
        ledger_path=ledger_path,
        dispatch_root=dispatch_root,
        report_root=report_root,
    )

    result = loop.run_once(poll_seconds=0, poll_interval_seconds=1)

    assert result.selected_work_item is None
    assert result.decision is not None
    assert result.decision.action == "stop"
    assert result.decision.reason == "No eligible work items after source-aware discovery"
    assert result.diagnostics["stop_reason"] == result.decision.reason

    repo_sources = result.diagnostics["discovery"]["repos"]["alpha"]["sources"]
    assert repo_sources["agent_assignment"]["extracted_candidate_count"] == 1
    assert repo_sources["cross_repo_todo"]["extracted_candidate_count"] == 1

    discovery_diagnostics = result.diagnostics.get("discovery_diagnostics")
    assert isinstance(discovery_diagnostics, dict)
    assert discovery_diagnostics["reason_code"] == "all_candidates_running_or_blocked"
    assert (
        discovery_diagnostics["explanation"]
        == "No eligible work items were selected because every discovered candidate was already running or blocked."
    )
    assert discovery_diagnostics["item_counts_per_source"]["alpha"]["agent_assignment"] == 1
    assert discovery_diagnostics["item_counts_per_source"]["alpha"]["cross_repo_todo"] == 1
    assert discovery_diagnostics["normalized_by_source"] == {"task": 2}
    assert discovery_diagnostics["rejected_counts"] == {"status_blocked": 1, "status_running": 1}
    assert discovery_diagnostics["details"] == {
        "total_discovered_candidates": 2,
        "total_rejected_candidates": 2,
        "sources_with_candidates": {"alpha": ["agent_assignment", "cross_repo_todo"]},
        "status_rejection_counts": {"status_blocked": 1, "status_running": 1},
    }

    rejected_candidates = discovery_diagnostics["rejected_candidates"]
    assert len(rejected_candidates) == 2
    assert rejected_candidates[0]["reason"] == "status_running"
    assert rejected_candidates[0]["status"] == "running"
    assert rejected_candidates[0]["title"] == "Wire orchestration discovery"
    assert rejected_candidates[1]["reason"] == "status_blocked"
    assert rejected_candidates[1]["status"] == "blocked"
    assert rejected_candidates[1]["title"] == "Blocked collector follow-up"
    assert rejected_candidates[1]["dependencies"] == ["shared-fixtures"]

    assert any("status_blocked=1" in note for note in result.notes)
    assert any("status_running=1" in note for note in result.notes)