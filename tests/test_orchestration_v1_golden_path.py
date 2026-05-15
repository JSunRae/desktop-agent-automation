from __future__ import annotations

import json
from pathlib import Path

from automation.orchestration_v1.loop import OrchestrationV1Loop
from automation.orchestration_v1.registry import load_registry


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_orchestration_v1_golden_path_selection_and_dispatch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "# TODO\n\n- docs cleanup for non-critical formatting\n",
    )
    _write(
        repo_root / "agent_reports" / "latest.md",
        "# Status\n\n- critical regression: failing schema validation in nightly check\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "golden-path-test",
        "description": "isolated v1 golden path",
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
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert result.run_id is not None
    assert result.selected_work_item.repo == "alpha"
    assert result.selected_work_item.source == "report"

    prompt_path = dispatch_root / "alpha" / f"{result.run_id}.prompt.md"
    envelope_path = dispatch_root / "alpha" / f"{result.run_id}.dispatch.json"
    assert prompt_path.is_file()
    assert envelope_path.is_file()


def test_orchestration_v1_structured_task_metadata_is_preserved(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "# Active Backlog\n\n"
        "- P1: stabilize flaky sync worker blocked by upstream API\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "structured-task-metadata",
        "description": "task metadata coverage",
        "global_constraints": {
            "max_active_workers_total": 1,
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
                    "blocked_by": ["shared-fixtures"],
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
    assert result.selected_work_item.source == "task"
    assert result.selected_work_item.metadata.get("priority") == "P1"
    assert result.selected_work_item.metadata.get("section") == "Active Backlog"
    assert result.selected_work_item.metadata.get("parse_mode") == "todo_markdown"
    assert result.selected_work_item.metadata.get("source_path") == "Todo.md"
    assert result.selected_work_item.dependencies == ["shared-fixtures", "upstream API"]


def test_orchestration_v1_reports_missing_task_source_candidates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(repo_root / "Todo.md", "# TODO\n\n- docs cleanup\n")

    registry_payload = {
        "version": 1,
        "workspace_id": "missing-task-source-diagnostics",
        "description": "discovery mismatch coverage",
        "global_constraints": {
            "max_active_workers_total": 1,
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
                "task_sources": ["plans/Todo.md"],
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
    assert result.decision.action == "stop"
    assert "source mismatch summary" in result.decision.reason
    assert "plans/Todo.md" in result.decision.reason
    assert any("nearby candidates: Todo.md" in note for note in result.notes)
    task_diag = result.diagnostics.get("discovery", {}).get("repos", {}).get("alpha", {}).get("sources", {}).get("task", {})
    assert task_diag.get("mismatch_reason") == "no_matching_files"
    assert "Todo.md" in task_diag.get("nearby_candidate_files", [])


def test_orchestration_v1_reports_matched_task_files_with_zero_items(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(repo_root / "Todo.md", "# TODO\n\n## Active Backlog\n\nNo bullets here.\n")

    registry_payload = {
        "version": 1,
        "workspace_id": "zero-item-task-diagnostics",
        "description": "matched task files with zero items",
        "global_constraints": {
            "max_active_workers_total": 1,
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
    assert result.decision.action == "stop"
    assert "found structured files but extracted no task candidates" in result.decision.reason
    assert "Todo.md" in result.decision.reason
    assert any("Todo.md" in note for note in result.notes)
    task_diag = result.diagnostics.get("discovery", {}).get("repos", {}).get("alpha", {}).get("sources", {}).get("task", {})
    assert task_diag.get("mismatch_reason") == "matched_files_without_extractable_items"
    assert task_diag.get("files_with_zero_items") == ["Todo.md"]


def test_orchestration_v1_pilot_allowlist_filters_and_dispatches_safe_class(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "# TODO\n\n"
        "- docs cleanup: README formatting typo\n"
        "- deploy gateway patch for live runtime\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "pilot-allowlist-test",
        "description": "allowlist gating",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
            "pilot_allowlist_enabled": True,
            "pilot_allowed_task_classes": ["docs_hygiene", "test_hardening", "diagnostics_analysis"],
            "pilot_allowed_categories": ["maintenance", "analysis", "bug"],
            "pilot_allowed_severities": ["low"],
            "pilot_allowed_sources": ["task", "handover", "report"],
            "pilot_blocked_title_terms": ["deploy", "gateway", "live"],
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": ["README.md"],
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert result.run_id is not None
    assert "docs cleanup" in result.selected_work_item.title.lower()
    selection_diag = result.diagnostics.get("selection", {})
    rejected_counts = selection_diag.get("rejected_counts", {})
    assert isinstance(rejected_counts, dict)
    assert rejected_counts.get("pilot_allowlist") == 1
    assert selection_diag.get("pilot_allowlist_reason_counts") == {"title_contains_blocked_term": 1}
    assert selection_diag.get("blocked_term_counts") == {"deploy": 1, "gateway": 1, "live": 1}

    prompt_path = dispatch_root / "alpha" / f"{result.run_id}.prompt.md"
    envelope_path = dispatch_root / "alpha" / f"{result.run_id}.dispatch.json"
    assert prompt_path.is_file()
    assert envelope_path.is_file()


def test_orchestration_v1_pilot_allowlist_tracks_reason_breakdown(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "# TODO\n\n"
        "- docs cleanup: README formatting typo\n"
        "- implement docs helper for onboarding\n"
        "- high readme typo cleanup\n"
        "- deploy notes cleanup in readme\n"
        "- rename local helper variable\n",
    )
    _write(
        repo_root / "agent_reports" / "latest.md",
        "# Status\n\n- docs cleanup from report\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "pilot-allowlist-reason-breakdown",
        "description": "allowlist reason diagnostics",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
            "pilot_allowlist_enabled": True,
            "pilot_allowed_task_classes": ["docs_hygiene"],
            "pilot_allowed_categories": ["maintenance"],
            "pilot_allowed_severities": ["low"],
            "pilot_allowed_sources": ["task"],
            "pilot_blocked_title_terms": ["deploy"],
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": ["README.md"],
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert "docs cleanup" in result.selected_work_item.title.lower()

    selection_diag = result.diagnostics.get("selection", {})
    assert selection_diag.get("rejected_counts") == {"pilot_allowlist": 5}
    assert selection_diag.get("pilot_allowlist_reason_counts") == {
        "category_not_allowed": 1,
        "severity_not_allowed": 1,
        "source_not_allowed": 1,
        "title_contains_blocked_term": 1,
        "task_class_not_allowed": 1,
    }
    assert selection_diag.get("blocked_term_counts") == {"deploy": 1}


def test_orchestration_v1_pilot_allowlist_allows_schema_docs_but_blocks_schema_migration(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "# TODO\n\n"
        "- document new schema usage in README\n"
        "- schema migration rollback checklist\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "pilot-allowlist-schema-calibration",
        "description": "schema phrase calibration",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
            "pilot_allowlist_enabled": True,
            "pilot_allowed_task_classes": ["docs_hygiene"],
            "pilot_allowed_categories": ["maintenance"],
            "pilot_allowed_severities": ["low"],
            "pilot_allowed_sources": ["task"],
            "pilot_blocked_title_terms": ["schema migration", "database migration"],
        },
        "repos": [
            {
                "repo_id": "alpha",
                "root_path": str(repo_root),
                "purpose": "test repo",
                "instruction_files": ["README.md"],
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert "document new schema usage" in result.selected_work_item.title.lower()

    selection_diag = result.diagnostics.get("selection", {})
    assert selection_diag.get("rejected_counts") == {"pilot_allowlist": 1}
    assert selection_diag.get("pilot_allowlist_reason_counts") == {"title_contains_blocked_term": 1}
    assert selection_diag.get("blocked_term_counts") == {"schema migration": 1}


def test_orchestration_v1_extracts_actionable_non_bullet_lines(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(
        repo_root / "Todo.md",
        "# Next Steps\n\n"
        "Fix flaky login test before release\n"
        "TODO: update onboarding docs for orchestrator\n"
        "[ ] verify worker telemetry in smoke run\n",
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "non-bullet-extraction-test",
        "description": "extract actionable non-bullet lines",
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
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert result.selected_work_item.source == "task"
    discovery = result.diagnostics.get("discovery", {})
    assert discovery.get("total_normalized_candidates", 0) == 3


def test_orchestration_v1_stop_reason_includes_source_pattern_mismatch_details(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    registry_payload = {
        "version": 1,
        "workspace_id": "source-mismatch-stop-reason-test",
        "description": "source mismatch diagnostics",
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
                "task_sources": ["tasks/open_tasks.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert result.decision.action == "stop"
    reason = str(result.decision.reason)
    assert "source mismatch summary" in reason
    assert "tasks/open_tasks.md" in reason

    mismatch_repos = result.diagnostics.get("discovery", {}).get("repos_with_source_mismatches", {})
    assert isinstance(mismatch_repos, dict)
    assert "alpha" in mismatch_repos


def test_orchestration_v1_extracts_json_report_candidates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(repo_root / "Todo.md", "# TODO\n")
    _write(
        repo_root / "agent_reports" / "latest.json",
        json.dumps(
            {
                "summary": "critical regression in nightly validation",
                "blockers": ["schema diff must be reviewed"],
                "next_recommended_actions": ["write minimal regression test"],
            }
        ),
    )

    registry_payload = {
        "version": 1,
        "workspace_id": "json-report-extraction-test",
        "description": "json report extraction",
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
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.json"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert result.selected_work_item.source == "report"
    report_diag = result.diagnostics.get("discovery", {}).get("repos", {}).get("alpha", {}).get("sources", {}).get("report", {})
    assert report_diag.get("extracted_candidate_count") == 3


def test_orchestration_v1_stop_reason_includes_matched_no_items_details(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_alpha"
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    _write(repo_root / "Todo.md", "# TODO\n")
    _write(repo_root / "agent_reports" / "latest.md", "This report has prose but no supported task markers.")

    registry_payload = {
        "version": 1,
        "workspace_id": "parse-gap-test",
        "description": "matched but no items",
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
                "task_sources": ["Todo.md"],
                "handover_locations": ["handover/**/*.md"],
                "report_locations": ["agent_reports/**/*.md"],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": ["training", "campaign"],
                    "protected_signal_files": ["state/running_jobs.json"],
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
    assert "report" in result.decision.reason
