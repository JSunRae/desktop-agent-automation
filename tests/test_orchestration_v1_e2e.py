from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from automation.north_star import REPO_DEPENDENCY_ORDER
from automation.orchestration_v1.loop import OrchestrationV1Loop
from automation.orchestration_v1.models import (
    RepoContextBundle,
    Severity,
    WorkCategory,
    WorkItem,
    WorkStatus,
)
from automation.orchestration_v1.registry import load_registry
from automation.orchestration_v1.vscode_pilot import poll_worker_outcome

pytestmark = pytest.mark.orchestration


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_loop(
    tmp_path: Path,
    *,
    repo_ids: list[str],
    global_constraints: dict[str, object] | None = None,
) -> tuple[OrchestrationV1Loop, Path, Path]:
    state_root = tmp_path / "state"
    dispatch_root = state_root / "dispatch_queue"
    report_root = state_root / "worker_reports"
    ledger_path = state_root / "global_ledger.jsonl"

    repos = []
    for repo_id in repo_ids:
        repo_root = tmp_path / repo_id
        repo_root.mkdir(parents=True, exist_ok=True)
        repos.append(
            {
                "repo_id": repo_id,
                "root_path": str(repo_root),
                "purpose": f"integration repo {repo_id}",
                "instruction_files": [],
                "task_sources": ["Todo.md"],
                "handover_locations": [],
                "report_locations": [],
                "validation_commands": ["pytest -q"],
                "safety_rules": {
                    "protected_process_patterns": [],
                    "protected_signal_files": [],
                    "allow_paths": [f"{repo_id}/**"],
                    "requires_explicit_approval_for": [],
                },
                "dependencies": {
                    "blocked_by": [],
                    "follow_up_targets": [],
                    "source_of_truth_for": [],
                },
            }
        )

    registry_payload = {
        "version": 1,
        "workspace_id": "orchestration-v1-e2e",
        "description": "deterministic orchestration_v1 integration coverage",
        "global_constraints": {
            "max_active_workers_total": 2,
            "max_active_workers_per_repo": 1,
            "loop_retry_limit": 3,
            "respect_repo_boundaries": True,
            "prefer_structured_sources": True,
            **(global_constraints or {}),
        },
        "repos": repos,
    }

    registry_path = tmp_path / "registry.json"
    _write(registry_path, json.dumps(registry_payload, indent=2))

    loop = OrchestrationV1Loop(
        registry=load_registry(registry_path),
        ledger_path=ledger_path,
        dispatch_root=dispatch_root,
        report_root=report_root,
    )
    return loop, dispatch_root, report_root


def _work_item(
    *,
    repo: str,
    work_item_id: str,
    title: str,
    severity: Severity,
    status: WorkStatus = WorkStatus.NEW,
    source: str = "task",
) -> WorkItem:
    return WorkItem(
        work_item_id=work_item_id,
        repo=repo,
        title=title,
        source=source,
        category=WorkCategory.BUG,
        severity=severity,
        dependencies=[],
        constraints=[],
        suggested_validation=["pytest -q"],
        status=status,
        confidence=0.9,
        metadata={"source_kind": "e2e_fixture"},
    )


def _mock_discovery(monkeypatch: pytest.MonkeyPatch, repo_items: dict[str, list[WorkItem]]) -> None:
    def _bundle(repo_id: str, root_path: str, count: int) -> RepoContextBundle:
        return RepoContextBundle(
            repo_id=repo_id,
            root_path=root_path,
            files_seen=["Todo.md"],
            task_texts=["fixture"],
            source_diagnostics={
                "task": {
                    "matched_files": ["Todo.md"],
                    "unmatched_entries": [],
                    "extracted_candidate_count": count,
                },
                "handover": {
                    "matched_files": [],
                    "unmatched_entries": [],
                    "extracted_candidate_count": 0,
                },
                "report": {
                    "matched_files": [],
                    "unmatched_entries": [],
                    "extracted_candidate_count": 0,
                },
            },
        )

    def _fake_collect_repo_context(repo):
        return _bundle(repo.repo_id, repo.root_path, len(repo_items.get(repo.repo_id, [])))

    def _fake_normalize_work_items(*, repo, bundle):
        return [copy.deepcopy(item) for item in repo_items.get(repo.repo_id, [])]

    monkeypatch.setattr("automation.orchestration_v1.loop.collect_repo_context", _fake_collect_repo_context)
    monkeypatch.setattr("automation.orchestration_v1.loop.normalize_work_items", _fake_normalize_work_items)


def _strict_report(run_id: str, repo_id: str, *, status: str = "success") -> str:
    payload = {
        "protocol": "pilot_response_v1",
        "run_id": run_id,
        "repo_id": repo_id,
        "status": status,
        "summary": "Structured worker completion",
        "body": {
            "files_changed": [{"path": "README.md", "reason": "documented outcome"}],
            "validation_run": [{"command": "pytest -q", "result": "pass", "notes": "green"}],
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
        "handover_written_to": "",
    }
    return (
        f"[[DAA_PILOT_RESPONSE_V1|START|run_id={run_id}|repo_id={repo_id}]]\n"
        f"{json.dumps(payload)}\n"
        f"[[DAA_PILOT_RESPONSE_V1|END|run_id={run_id}|repo_id={repo_id}]]"
    )


def _terminal_rows(loop: OrchestrationV1Loop, event_name: str) -> list[dict[str, object]]:
    return [row for row in loop.ledger.read_rows() if str(row.get("event", "")) == event_name]


def test_orchestration_v1_e2e_happy_path_records_completed_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, dispatch_root, report_root = _build_loop(tmp_path, repo_ids=["alpha"])
    _mock_discovery(
        monkeypatch,
        {
            "alpha": [
                _work_item(
                    repo="alpha",
                    work_item_id="alpha-1",
                    title="Fix worker integration regression",
                    severity=Severity.HIGH,
                )
            ]
        },
    )
    monkeypatch.setattr(loop, "_new_run_id", lambda repo_id: f"{repo_id}-run01")

    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)

    assert result.run_id == "alpha-run01"
    assert result.selected_work_item is not None
    assert result.decision is not None
    assert result.decision.action == "wait"

    prompt_path = dispatch_root / "alpha" / "alpha-run01.prompt.md"
    envelope_path = dispatch_root / "alpha" / "alpha-run01.dispatch.json"
    assert prompt_path.is_file()
    assert envelope_path.is_file()

    _write(report_root / "alpha-run01.md", _strict_report("alpha-run01", "alpha", status="success"))
    polled = poll_worker_outcome(
        run_id="alpha-run01",
        repo_id="alpha",
        repo_root=loop.repo_index["alpha"].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )

    assert polled.report is not None
    assert polled.report.status.value == "success"
    decision = loop.record_report_and_decision(
        run_id="alpha-run01",
        selected=result.selected_work_item,
        report=polled.report,
        response_meta={"source": polled.source, "parse_mode": polled.parse_mode},
    )

    completed = _terminal_rows(loop, "run_completed")
    assert decision.action == "accept"
    assert loop.ledger.has_terminal_event("alpha-run01") is True
    assert completed
    payload = completed[-1]["payload"]
    assert isinstance(payload, dict)
    assert payload["run_id"] == "alpha-run01"
    assert payload["report"]["status"] == "success"


def test_orchestration_v1_e2e_parse_failure_marks_failed_and_advances_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, _dispatch_root, report_root = _build_loop(
        tmp_path,
        repo_ids=["alpha"],
        global_constraints={"loop_retry_limit": 1},
    )
    _mock_discovery(
        monkeypatch,
        {
            "alpha": [
                _work_item(
                    repo="alpha",
                    work_item_id="alpha-1",
                    title="Primary item with malformed completion",
                    severity=Severity.HIGH,
                ),
                _work_item(
                    repo="alpha",
                    work_item_id="alpha-2",
                    title="Fallback item after parser failure",
                    severity=Severity.MEDIUM,
                ),
            ]
        },
    )
    run_ids = iter(["alpha-run01", "alpha-run02"])
    monkeypatch.setattr(loop, "_new_run_id", lambda repo_id: next(run_ids))

    first = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert first.run_id == "alpha-run01"
    assert first.selected_work_item is not None

    _write(report_root / "alpha-run01.md", "Malformed panel response without strict markers")
    polled = poll_worker_outcome(
        run_id="alpha-run01",
        repo_id="alpha",
        repo_root=loop.repo_index["alpha"].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )

    assert polled.report is not None
    assert polled.source == "malformed_report"
    assert polled.response_diagnostics["primary_rejection"]["reason"] == "E_MARKER_START_INVALID"

    decision = loop.record_report_and_decision(
        run_id="alpha-run01",
        selected=first.selected_work_item,
        report=polled.report,
        response_meta={"source": polled.source, "response_diagnostics": polled.response_diagnostics},
    )

    failed = _terminal_rows(loop, "run_failed")
    assert decision.action == "stop"
    assert failed
    failed_payload = failed[-1]["payload"]
    assert isinstance(failed_payload, dict)
    assert failed_payload["work_item_id"] == "alpha-1"

    second = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert second.selected_work_item is not None
    assert second.selected_work_item.work_item_id == "alpha-2"
    assert second.diagnostics["selection"]["rejected_counts"]["retry_limit"] == 1


def test_orchestration_v1_e2e_no_eligible_work_items_reports_stop_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, _dispatch_root, _report_root = _build_loop(tmp_path, repo_ids=["alpha"])
    _mock_discovery(
        monkeypatch,
        {
            "alpha": [
                _work_item(
                    repo="alpha",
                    work_item_id="alpha-blocked",
                    title="Blocked integration task",
                    severity=Severity.BLOCKER,
                    status=WorkStatus.BLOCKED,
                )
            ]
        },
    )

    result = loop.run_once(poll_seconds=0, poll_interval_seconds=1)

    assert result.selected_work_item is None
    assert result.decision is not None
    assert result.decision.action == "stop"
    assert isinstance(result.diagnostics.get("stop_reason"), str)
    assert result.diagnostics["stop_reason"]
    assert result.diagnostics["selection"]["rejected_counts"]["status_blocked"] == 1


def test_orchestration_v1_e2e_allowlist_gating_tracks_blocked_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, _dispatch_root, _report_root = _build_loop(
        tmp_path,
        repo_ids=["alpha"],
        global_constraints={
            "pilot_allowlist_enabled": True,
            "pilot_allowed_task_classes": ["docs_hygiene"],
            "pilot_allowed_categories": ["bug", "maintenance", "analysis"],
            "pilot_allowed_severities": ["low"],
            "pilot_allowed_sources": ["task"],
            "pilot_blocked_title_terms": ["schema migration"],
        },
    )
    _mock_discovery(
        monkeypatch,
        {
            "alpha": [
                _work_item(
                    repo="alpha",
                    work_item_id="alpha-allowlist",
                    title="Schema migration docs cleanup",
                    severity=Severity.LOW,
                )
            ]
        },
    )

    result = loop.run_once(poll_seconds=0, poll_interval_seconds=1)

    assert result.selected_work_item is None
    assert result.decision is not None
    assert result.decision.action == "stop"
    assert result.diagnostics["selection"]["blocked_term_counts"]["schema migration"] == 1
    assert result.diagnostics["selection"]["pilot_allowlist_reason_counts"]["title_contains_blocked_term"] == 1


def test_orchestration_v1_e2e_multi_repo_prioritises_contracts_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, _dispatch_root, _report_root = _build_loop(tmp_path, repo_ids=["contracts", "Trading"])
    _mock_discovery(
        monkeypatch,
        {
            "contracts": [
                _work_item(
                    repo="contracts",
                    work_item_id="contracts-1",
                    title="Fix blocking contract drift",
                    severity=Severity.BLOCKER,
                )
            ],
            "Trading": [
                _work_item(
                    repo="Trading",
                    work_item_id="trading-1",
                    title="Handle high-priority downstream follow-up",
                    severity=Severity.HIGH,
                )
            ],
        },
    )
    monkeypatch.setattr(loop, "_new_run_id", lambda repo_id: f"{repo_id.lower()}-run01")

    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)

    assert REPO_DEPENDENCY_ORDER[0] == "contracts"
    assert result.selected_work_item is not None
    assert result.selected_work_item.repo == "contracts"
    assert result.diagnostics["selection"]["eligible_ranked"][0]["repo"] == "contracts"
