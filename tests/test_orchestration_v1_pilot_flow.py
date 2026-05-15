from __future__ import annotations

import json
from pathlib import Path

from automation.orchestration_v1.loop import OrchestrationV1Loop
from automation.orchestration_v1.registry import load_registry
from automation.orchestration_v1.vscode_pilot import (
    build_window_preflight,
    dispatch_prompt_to_repo_window,
    inspect_repo_window_targeting,
    poll_worker_outcome,
    prepare_explicit_fallback_targeting,
)
from automation.orchestration_v1.worker_protocol import (
    STRICT_END_TEMPLATE,
    STRICT_PROTOCOL,
    STRICT_START_TEMPLATE,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "orchestration_v1"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _hwnd_from_window_id(window_id: str) -> int:
    return int(str(window_id).split(":", 1)[1])


def _load_targeting_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _materialize_targeting_windows(rows: list[dict]) -> list[dict]:
    materialized = []
    for row in rows:
        item = dict(row)
        item["dispatch_reference"] = _FakeWindow(str(item["title"]), _hwnd_from_window_id(str(item["window_id"])))
        materialized.append(item)
    return materialized


def _run_targeting_fixture(monkeypatch, fixture_name: str) -> tuple[dict, dict]:
    fixture = _load_targeting_fixture(fixture_name)
    foreground_window_id = str(fixture.get("foreground_window_id") or "")
    foreground_hwnd = _hwnd_from_window_id(foreground_window_id) if foreground_window_id else 0
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_foreground_window", lambda: foreground_hwnd)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_root_window", lambda hwnd: hwnd)
    diagnostics = inspect_repo_window_targeting(
        repo_id=str(fixture["repo_id"]),
        repo_root=str(fixture["repo_root"]),
        windows=_materialize_targeting_windows(list(fixture.get("windows") or [])),
        omitted_windows=list(fixture.get("omitted_windows") or []),
    )
    return fixture, diagnostics


def _build_test_loop(tmp_path: Path) -> tuple[OrchestrationV1Loop, Path, Path]:
    repo_root = tmp_path / "repo_alpha"
    dispatch_root = tmp_path / "state" / "dispatch_queue"
    report_root = tmp_path / "state" / "worker_reports"
    ledger_path = tmp_path / "state" / "global_ledger.jsonl"

    _write(repo_root / "Todo.md", "# TODO\n\n- docs typo cleanup in readme\n")

    registry_payload = {
        "version": 1,
        "workspace_id": "pilot-flow-test",
        "description": "isolated pilot flow",
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
            "pilot_blocked_title_terms": ["deploy", "live", "migration"],
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
    return loop, dispatch_root, report_root


def test_deferred_dispatch_then_file_response_finalize(tmp_path: Path) -> None:
    loop, dispatch_root, report_root = _build_test_loop(tmp_path)

    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id is not None
    assert result.selected_work_item is not None
    assert result.decision is not None and result.decision.action == "wait"

    run_id = result.run_id
    repo = result.selected_work_item.repo

    # Accept alias status "completed" and map to success.
    _write(
        report_root / f"{run_id}.json",
        json.dumps(
            {
                "status": "completed",
                "summary": "Completed analysis and provided next steps",
                "files_changed": [],
                "validation_run": [{"command": "pytest -q", "result": "pass", "notes": "ok"}],
            }
        ),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=2,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
    )

    assert polled.report is not None
    assert polled.report.status.value == "success"
    decision = loop.record_report_and_decision(
        run_id=run_id,
        selected=result.selected_work_item,
        report=polled.report,
        response_meta={"source": polled.source},
    )
    assert decision.action == "accept"

    rows = loop.ledger.read_rows()
    terminal = [r for r in rows if str(r.get("event", "")) == "run_completed"]
    assert terminal

    prompt_path = dispatch_root / repo / f"{run_id}.prompt.md"
    assert prompt_path.is_file()


def test_malformed_report_is_not_left_hanging(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)

    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id is not None
    assert result.selected_work_item is not None

    run_id = result.run_id
    repo = result.selected_work_item.repo

    _write(report_root / f"{run_id}.md", "This file exists but has no structured completion payload")

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
    )

    assert polled.report is not None
    assert polled.source == "malformed_report"
    assert polled.report.status.value == "failed"

    decision = loop.record_report_and_decision(
        run_id=run_id,
        selected=result.selected_work_item,
        report=polled.report,
        response_meta={"source": polled.source},
    )
    assert decision.action == "stop"

    rows = loop.ledger.read_rows()
    failed = [r for r in rows if str(r.get("event", "")) == "run_failed"]
    assert failed


def test_poll_worker_outcome_malformed_candidate_returns_synthetic_failed_report(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    raw = "This file exists but has no structured completion payload"
    _write(report_root / f"{run_id}.md", raw)

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
    )

    assert polled.source == "malformed_report"
    assert polled.parse_mode == "failed_parse"
    assert polled.report is not None
    assert polled.report.status.value == "failed"
    assert polled.report.summary == "Malformed worker report"
    assert polled.report.blockers == ["malformed_report"]
    assert polled.report.raw_text == raw


def test_poll_worker_outcome_rejected_candidate_returns_synthetic_failed_report(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    raw = _strict_payload("wrong-run-123", repo, status="success")
    _write(report_root / f"{run_id}.md", raw)

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )

    assert polled.source == "malformed_report"
    assert polled.parse_mode == "strict_failed_parse"
    assert polled.report is not None
    assert polled.report.status.value == "failed"
    assert polled.report.summary == "Malformed worker report"
    assert polled.report.blockers == ["malformed_report"]
    assert polled.report.raw_text == raw


def test_poll_worker_outcome_timeout_only_keeps_report_none(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=0,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
    )

    assert polled.source == "timeout"
    assert polled.parse_mode is None
    assert polled.report is None
    assert polled.malformed_seen is False
    assert polled.response_diagnostics.get("waiting_status", {}).get("state") == "timeout"


def _strict_payload(run_id: str, repo_id: str, status: str = "success") -> str:
    body = {
        "protocol": STRICT_PROTOCOL,
        "run_id": run_id,
        "repo_id": repo_id,
        "status": status,
        "summary": "Strict contract response",
        "body": {
            "files_changed": [{"path": "README.md", "reason": "docs update"}],
            "validation_run": [{"command": "pytest -q", "result": "pass", "notes": "ok"}],
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
    }
    return (
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo_id)
        + "\n"
        + json.dumps(body)
        + "\n"
        + STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo_id)
    )


def test_strict_response_accepts_marker_framed_report(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    _write(report_root / f"{run_id}.md", _strict_payload(run_id, repo, status="success"))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=2,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.report.status.value == "success"
    assert polled.parse_mode == "strict_marked_json"
    assert polled.response_diagnostics.get("strict_mode") is True


def test_strict_response_accepts_minimal_known_good_reply(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    minimal_payload = {
        "protocol": STRICT_PROTOCOL,
        "run_id": run_id,
        "repo_id": repo,
        "status": "partial",
        "summary": "ACK: scoped task received.",
        "body": {
            "files_changed": [],
            "validation_run": [{"command": "not_run_in_first_reply", "result": "not_run", "notes": "triage_only"}],
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
        "handover_written_to": "",
    }
    _write(
        report_root / f"{run_id}.md",
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo)
        + "\n"
        + json.dumps(minimal_payload)
        + "\n"
        + STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.report.status.value == "partial"
    assert polled.response_diagnostics.get("schema") == "pilot_poll_diagnostics_v1"
    waiting = polled.response_diagnostics.get("waiting_status", {})
    assert waiting.get("state") == "accepted"


def test_strict_response_rejects_run_id_mismatch(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    _write(report_root / f"{run_id}.md", _strict_payload("wrong-run-123", repo, status="success"))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    reasons = [row.get("reason") for row in polled.response_diagnostics.get("rejected_candidates", [])]
    assert "E_RUN_ID_MISMATCH" in reasons
    hints = polled.response_diagnostics.get("close_but_invalid_hints", [])
    assert any(row.get("hint_code") == "id_mismatch" for row in hints)


def test_strict_response_rejects_missing_markers(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    _write(report_root / f"{run_id}.json", json.dumps({"status": "success", "summary": "loose"}))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=result.selected_work_item.repo,
        repo_root=loop.repo_index[result.selected_work_item.repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    reasons = [row.get("reason") for row in polled.response_diagnostics.get("rejected_candidates", [])]
    assert "E_MARKER_START_INVALID" in reasons
    primary = polled.response_diagnostics.get("primary_rejection", {})
    assert primary.get("reason") == "E_MARKER_START_INVALID"
    assert primary.get("hint_code") == "missing_or_duplicate_start_marker"
    guidance = polled.response_diagnostics.get("operator_guidance", {})
    assert guidance.get("next_step") == "resend_clean_marker_framed_json"


def test_strict_response_rejects_payload_run_id_mismatch(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    payload = {
        "protocol": STRICT_PROTOCOL,
        "run_id": "stale-run-id",
        "repo_id": repo,
        "status": "success",
        "summary": "payload stale id",
        "body": {
            "files_changed": [],
            "validation_run": [],
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
    }
    _write(
        report_root / f"{run_id}.md",
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo)
        + "\n"
        + json.dumps(payload)
        + "\n"
        + STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    rejected = polled.response_diagnostics.get("rejected_candidates", [])
    reasons = [row.get("reason") for row in rejected]
    assert "E_PAYLOAD_RUN_ID_MISMATCH" in reasons
    mismatch = next(row for row in rejected if row.get("reason") == "E_PAYLOAD_RUN_ID_MISMATCH")
    assert mismatch.get("detail", {}).get("expected_run_id") == run_id
    assert mismatch.get("detail", {}).get("actual_run_id") == "stale-run-id"


def test_strict_response_rejects_marker_framed_malformed_json_payload(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    _write(
        report_root / f"{run_id}.md",
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo)
        + "\n"
        + '{"protocol":"pilot_response_v1","run_id":"'
        + run_id
        + '","repo_id":"'
        + repo
        + '","status":"success","summary":"x","body":{'
        + "\n"
        + STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    rejected = polled.response_diagnostics.get("rejected_candidates", [])
    reasons = [row.get("reason") for row in rejected]
    assert "E_PAYLOAD_NOT_JSON" in reasons
    malformed = next(row for row in rejected if row.get("reason") == "E_PAYLOAD_NOT_JSON")
    assert isinstance(malformed.get("detail", {}).get("json_error_pos"), int)
    assert isinstance(malformed.get("detail", {}).get("json_error_lineno"), int)
    assert isinstance(malformed.get("detail", {}).get("json_error_colno"), int)


def test_strict_response_rejects_markdown_fenced_payload_with_actionable_hint(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    raw = "```\n" + _strict_payload(run_id, repo, status="partial") + "\n```"
    _write(report_root / f"{run_id}.md", raw)

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )

    assert polled.report is not None
    assert polled.source == "malformed_report"
    primary = polled.response_diagnostics.get("primary_rejection", {})
    assert primary.get("reason") == "E_OUTSIDE_MARKER_TEXT"
    assert primary.get("hint_code") == "outside_marker_text"
    assert primary.get("operator_next_step") == "resend_clean_marker_framed_json"
    assert primary.get("detail", {}).get("outside_text_preview") == "``` ```"


def test_strict_response_rejects_json_array_payload_with_actionable_hint(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    raw = (
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo)
        + "\n"
        + json.dumps([{"protocol": STRICT_PROTOCOL, "run_id": run_id, "repo_id": repo}])
        + "\n"
        + STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo)
    )
    _write(report_root / f"{run_id}.md", raw)

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )

    assert polled.report is not None
    assert polled.source == "malformed_report"
    primary = polled.response_diagnostics.get("primary_rejection", {})
    assert primary.get("reason") == "E_PAYLOAD_NOT_OBJECT"
    assert primary.get("hint_code") == "payload_not_object"
    assert primary.get("operator_next_step") == "resend_valid_json_object"


def test_strict_response_rejects_partial_marker_payload(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    _write(
        report_root / f"{run_id}.md",
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo)
        + "\n"
        + json.dumps(
            {
                "protocol": STRICT_PROTOCOL,
                "run_id": run_id,
                "repo_id": repo,
                "status": "success",
                "summary": "partial payload",
                "body": {
                    "files_changed": [],
                    "validation_run": [],
                    "blockers": [],
                    "risks": [],
                    "next_recommended_actions": [],
                },
            }
        ),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    rejected = polled.response_diagnostics.get("rejected_candidates", [])
    reasons = [row.get("reason") for row in rejected]
    assert "E_MARKER_END_INVALID" in reasons
    partial = next(row for row in rejected if row.get("reason") == "E_MARKER_END_INVALID")
    assert partial.get("detail", {}).get("end_marker_count") == 0


def test_duplicate_candidates_are_rejected_with_observable_metadata(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    raw = "This file exists but has no structured completion payload"
    _write(report_root / f"{run_id}.md", raw)
    _write(report_root / repo / f"{run_id}.md", raw)

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=0,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=False,
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    rejected = polled.response_diagnostics.get("rejected_candidates", [])
    reasons = [row.get("reason") for row in rejected]
    assert "E_PARSE_FAILED" in reasons
    assert "E_DUPLICATE_CANDIDATE" in reasons

    duplicate = next(row for row in rejected if row.get("reason") == "E_DUPLICATE_CANDIDATE")
    assert isinstance(duplicate.get("candidate_sha256"), str) and duplicate.get("candidate_sha256")
    assert duplicate.get("raw_len") == len(raw)
    assert polled.response_diagnostics.get("channel_attempts", {}).get("report_file", 0) >= 1
    assert isinstance(polled.response_diagnostics.get("candidate_events"), list)


def _strict_payload_custom(
    *,
    run_id: str,
    repo_id: str,
    status: str = "partial",
    files_changed: list[dict] | None = None,
    validation_result: str = "not_run",
    include_validation: bool = True,
    handover_written_to: str = "",
) -> str:
    payload = {
        "protocol": STRICT_PROTOCOL,
        "run_id": run_id,
        "repo_id": repo_id,
        "status": status,
        "summary": "Sandbox triage reply",
        "body": {
            "files_changed": files_changed or [],
            "validation_run": (
                [{"command": "not_run_in_first_reply", "result": validation_result, "notes": "sandbox"}]
                if include_validation
                else []
            ),
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
        "handover_written_to": handover_written_to,
    }
    return (
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo_id)
        + "\n"
        + json.dumps(payload)
        + "\n"
        + STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo_id)
    )


def test_sandbox_mode_accepts_known_good_triage_only_payload(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    allowed_path = report_root / f"{run_id}.md"
    _write(allowed_path, _strict_payload_custom(run_id=run_id, repo_id=repo, status="partial"))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
        sandbox_mode=True,
        sandbox_allowed_report_paths=[str(allowed_path.resolve(strict=False))],
    )
    assert polled.report is not None
    assert polled.source == "report_file"
    assert polled.report.status.value == "partial"
    assert polled.response_diagnostics.get("sandbox_mode") is True


def test_sandbox_mode_rejects_files_changed(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    path = report_root / f"{run_id}.md"
    _write(
        path,
        _strict_payload_custom(
            run_id=run_id,
            repo_id=repo,
            status="partial",
            files_changed=[{"path": "README.md", "reason": "changed"}],
        ),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
        sandbox_mode=True,
        sandbox_allowed_report_paths=[str(path.resolve(strict=False))],
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    reasons = [row.get("reason") for row in polled.response_diagnostics.get("rejected_candidates", [])]
    assert "E_SANDBOX_FILES_CHANGED" in reasons


def test_sandbox_mode_rejects_validation_execution(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    path = report_root / f"{run_id}.md"
    _write(path, _strict_payload_custom(run_id=run_id, repo_id=repo, status="partial", validation_result="pass"))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
        sandbox_mode=True,
        sandbox_allowed_report_paths=[str(path.resolve(strict=False))],
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    reasons = [row.get("reason") for row in polled.response_diagnostics.get("rejected_candidates", [])]
    assert "E_SANDBOX_VALIDATION_EXECUTED" in reasons


def test_sandbox_mode_requires_validation_rows(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    path = report_root / f"{run_id}.md"
    _write(path, _strict_payload_custom(run_id=run_id, repo_id=repo, status="partial", include_validation=False))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
        sandbox_mode=True,
        sandbox_allowed_report_paths=[str(path.resolve(strict=False))],
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    primary = polled.response_diagnostics.get("primary_rejection", {})
    assert primary.get("reason") == "E_SANDBOX_VALIDATION_REQUIRED"
    assert primary.get("hint_code") == "sandbox_validation_required"


def test_sandbox_mode_rejects_handover_output(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    path = report_root / f"{run_id}.md"
    _write(
        path,
        _strict_payload_custom(
            run_id=run_id,
            repo_id=repo,
            status="partial",
            handover_written_to="handover/report.md",
        ),
    )

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
        sandbox_mode=True,
        sandbox_allowed_report_paths=[str(path.resolve(strict=False))],
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    primary = polled.response_diagnostics.get("primary_rejection", {})
    assert primary.get("reason") == "E_SANDBOX_HANDOVER_NOT_ALLOWED"
    assert primary.get("hint_code") == "sandbox_handover_not_allowed"


def test_sandbox_mode_rejects_unapproved_report_path(tmp_path: Path) -> None:
    loop, _dispatch_root, report_root = _build_test_loop(tmp_path)
    result = loop.run_once(poll_seconds=-1, poll_interval_seconds=1)
    assert result.run_id and result.selected_work_item

    run_id = result.run_id
    repo = result.selected_work_item.repo
    disallowed_path = report_root / repo / f"{run_id}.md"
    allowed_other_path = report_root / f"{run_id}.md"
    _write(disallowed_path, _strict_payload_custom(run_id=run_id, repo_id=repo, status="partial"))

    polled = poll_worker_outcome(
        run_id=run_id,
        repo_id=repo,
        repo_root=loop.repo_index[repo.lower()].root_path,
        report_root=report_root,
        poll_seconds=1,
        poll_interval_seconds=1,
        allow_panel_fallback=False,
        strict_mode=True,
        sandbox_mode=True,
        sandbox_allowed_report_paths=[str(allowed_other_path.resolve(strict=False))],
    )
    assert polled.report is not None
    assert polled.source == "malformed_report"
    reasons = [row.get("reason") for row in polled.response_diagnostics.get("rejected_candidates", [])]
    assert "E_SANDBOX_REPORT_PATH_NOT_ALLOWED" in reasons


class _FakeWindow:
    def __init__(self, title: str, handle: int) -> None:
        self.Name = title
        self.NativeWindowHandle = handle


def test_window_targeting_one_clear_repo_match(monkeypatch) -> None:
    windows = [
        _FakeWindow("Chat - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 101),
        _FakeWindow("Other Task - beta (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 202),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(repo_id="alpha", repo_root="C:/repos/alpha")
    assert diagnostics["summary"]["discovered_windows"] == 2
    assert diagnostics["summary"]["matched_windows"] == 1
    assert diagnostics["summary"]["eligible_for_dispatch"] is True
    assert diagnostics["selection"]["reason_code"] == "selected_single_match"


def test_window_targeting_ambiguous_windows_require_explicit_selection(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 111),
        _FakeWindow("Task B - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 112),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_foreground_window", lambda: 111)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_root_window", lambda hwnd: hwnd)

    diagnostics = inspect_repo_window_targeting(repo_id="alpha", repo_root="C:/repos/alpha")
    assert diagnostics["summary"]["matched_windows"] == 2
    assert diagnostics["summary"]["eligible_for_dispatch"] is False
    assert diagnostics["selection"]["reason_code"] == "ambiguous_repo_window"
    assert diagnostics["selection"]["ambiguous_window_ids"] == ["hwnd:111", "hwnd:112"]
    assert diagnostics["summary"]["foreground_window_id"] == "hwnd:111"
    matched = diagnostics["matched_windows"]
    assert matched[0]["title_duplicate_count"] == 1
    assert matched[0]["is_foreground"] is True
    assert matched[1]["is_foreground"] is False
    guidance = diagnostics["operator_guidance"]
    assert guidance["issue"] == "ambiguous_repo_window"
    assert guidance["next_step"] == "run_readiness_only_with_exact_window_id"
    commands = guidance["exact_target_commands"]
    assert commands[0]["window_id"] == "hwnd:111"
    assert "--pilot-readiness-only --pilot-readiness-repo alpha --pilot-window-id hwnd:111 --json" in commands[0]["readiness_command"]
    assert "--pilot-live-dispatch --pilot-dry-run --pilot-dry-run-repo alpha --pilot-window-id hwnd:111 --json" in commands[0]["dry_run_command"]


def test_window_targeting_fixture_ambiguous_equal_strength_preserves_stop(monkeypatch) -> None:
    fixture, diagnostics = _run_targeting_fixture(monkeypatch, "targeting_ambiguous_equal_strength.json")

    expected = fixture["expected"]
    assert diagnostics["selection"]["reason_code"] == expected["reason_code"]
    assert diagnostics["summary"]["eligible_for_dispatch"] is expected["eligible_for_dispatch"]
    assert diagnostics["summary"]["matched_windows"] == expected["matched_windows"]
    assert diagnostics["summary"]["win32_only_matches"] == expected["win32_only_matches"]
    assert diagnostics["selection"]["selected_window_id"] is expected["selected_window_id"]


def test_window_targeting_fixture_win32_only_target_surfaces_real_case(monkeypatch) -> None:
    fixture, diagnostics = _run_targeting_fixture(monkeypatch, "targeting_win32_only_with_self_repo_visible.json")

    expected = fixture["expected"]
    assert diagnostics["selection"]["reason_code"] == expected["reason_code"]
    assert diagnostics["summary"]["eligible_for_dispatch"] is expected["eligible_for_dispatch"]
    assert diagnostics["summary"]["matched_windows"] == expected["matched_windows"]
    assert diagnostics["summary"]["win32_only_matches"] == expected["win32_only_matches"]
    assert diagnostics["selection"]["selected_window_id"] == expected["selected_window_id"]

    protected_row = next(
        row for row in diagnostics["windows"] if row["window_id"] == expected["protected_visible_window_id"]
    )
    assert protected_row["dispatch_eligible"] is False
    assert "protected_repo_context_rejected" in (protected_row.get("reasons") or [])


def test_window_targeting_fixture_ranked_non_auxiliary_reduces_avoidable_ambiguity(monkeypatch) -> None:
    fixture, diagnostics = _run_targeting_fixture(monkeypatch, "targeting_ranked_non_auxiliary_preferred.json")

    expected = fixture["expected"]
    assert diagnostics["selection"]["reason_code"] == expected["reason_code"]
    assert diagnostics["summary"]["eligible_for_dispatch"] is expected["eligible_for_dispatch"]
    assert diagnostics["summary"]["matched_windows"] == expected["matched_windows"]
    assert diagnostics["summary"]["win32_only_matches"] == expected["win32_only_matches"]
    assert diagnostics["selection"]["selected_window_id"] == expected["selected_window_id"]


def test_window_targeting_prefers_visible_non_auxiliary_candidate(monkeypatch) -> None:
    windows = [
        _FakeWindow("Chat - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 1201),
        _FakeWindow("Task B - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 1202),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_foreground_window", lambda: 1201)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot.enumerate_vscode_windows_win32",
        lambda: {
            "summary": {"vscode_title_matches": 2},
            "windows": [
                {
                    "window_id": "hwnd:1201",
                    "hwnd": 1201,
                    "title": windows[0].Name,
                    "class_name": "Chrome_WidgetWin_1",
                    "is_vscode_title_match": True,
                    "is_visible": True,
                    "is_minimized": False,
                    "is_cloaked": False,
                    "cloaked_raw": 0,
                    "inclusion_reason": "included_vscode_visible",
                },
                {
                    "window_id": "hwnd:1202",
                    "hwnd": 1202,
                    "title": windows[1].Name,
                    "class_name": "Chrome_WidgetWin_1",
                    "is_vscode_title_match": True,
                    "is_visible": True,
                    "is_minimized": False,
                    "is_cloaked": False,
                    "cloaked_raw": 0,
                    "inclusion_reason": "included_vscode_visible",
                },
            ],
        },
    )

    diagnostics = inspect_repo_window_targeting(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        windows=[
            {
                "window_id": "hwnd:1201",
                "window_index": 1,
                "title": windows[0].Name,
                "parsed_repo": "alpha",
                "normalized_parsed_repo": "alpha",
                "dispatch_reference": windows[0],
                "is_visible": True,
                "is_minimized": False,
                "is_cloaked": False,
                "inclusion_reason": "included_by_uia",
                "win32_lookup": "matched",
            },
            {
                "window_id": "hwnd:1202",
                "window_index": 2,
                "title": windows[1].Name,
                "parsed_repo": "alpha",
                "normalized_parsed_repo": "alpha",
                "dispatch_reference": windows[1],
                "is_visible": True,
                "is_minimized": False,
                "is_cloaked": False,
                "inclusion_reason": "included_by_uia",
                "win32_lookup": "matched",
            },
        ],
    )
    assert diagnostics["summary"]["matched_windows"] == 2
    assert diagnostics["summary"]["eligible_for_dispatch"] is True
    assert diagnostics["selection"]["reason_code"] == "selected_best_ranked_match"
    assert diagnostics["selection"]["selected_window_id"] == "hwnd:1202"


def test_window_targeting_reports_win32_only_target_instead_of_no_match(monkeypatch) -> None:
    windows = [
        _FakeWindow("Chat - desktop-agent-automation - Visual Studio Code", 1301),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(
        repo_id="TF",
        repo_root="C:/repos/TF",
        windows=[
            {
                "window_id": "hwnd:1301",
                "window_index": 1,
                "title": windows[0].Name,
                "parsed_repo": "desktop-agent-automation",
                "normalized_parsed_repo": "desktop-agent-automation",
                "dispatch_reference": windows[0],
                "is_visible": True,
                "is_minimized": False,
                "is_cloaked": False,
                "inclusion_reason": "included_by_uia",
                "win32_lookup": "matched",
            },
        ],
        omitted_windows=[
            {
                "window_id": "hwnd:7999",
                "title": "Task X - TF (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code",
                "is_visible": True,
                "is_minimized": False,
                "is_cloaked": True,
                "cloaked_raw": 2,
                "inclusion_reason": "omitted_from_uia_snapshot",
            }
        ],
    )

    assert diagnostics["summary"]["matched_windows"] == 0
    assert diagnostics["summary"]["win32_only_matches"] == 1
    assert diagnostics["selection"]["reason_code"] == "repo_window_detected_win32_only"
    assert diagnostics["selection"]["selected_window_id"] == "hwnd:7999"
    guidance = diagnostics["operator_guidance"]
    assert guidance["issue"] == "repo_window_detected_win32_only"
    assert guidance["exact_target_commands"][0]["window_id"] == "hwnd:7999"


def test_window_targeting_title_token_fallback_reduces_no_match(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha - Visual Studio Code", 1401),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        windows=[
            {
                "window_id": "hwnd:1401",
                "window_index": 1,
                "title": windows[0].Name,
                "parsed_repo": "",
                "normalized_parsed_repo": "",
                "dispatch_reference": windows[0],
            }
        ],
    )

    assert diagnostics["summary"]["matched_windows"] == 1
    assert diagnostics["summary"]["eligible_for_dispatch"] is True
    assert diagnostics["selection"]["reason_code"] == "selected_single_match"
    assert diagnostics["matched_windows"][0]["match_method"] == "title_token_exact"


def test_window_targeting_duplicate_titles_include_disambiguation_evidence(monkeypatch) -> None:
    title = "Chat - desktop-agent-automation (Workspace) - Visual Studio Code"
    windows = [
        _FakeWindow(title, 3001),
        _FakeWindow(title, 3002),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_foreground_window", lambda: 3002)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_root_window", lambda hwnd: hwnd)

    diagnostics = inspect_repo_window_targeting(
        repo_id="desktop-agent-automation",
        repo_root="C:/repos/desktop-agent-automation",
    )
    assert diagnostics["summary"]["matched_windows"] == 2
    assert diagnostics["selection"]["reason_code"] == "ambiguous_repo_window"
    matched = diagnostics["matched_windows"]
    assert all(row["title_duplicate_count"] == 2 for row in matched)
    assert any(row["is_foreground"] is True for row in matched)
    assert any(row["is_foreground"] is False for row in matched)


def test_window_targeting_no_matches(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - beta (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 301),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(repo_id="alpha", repo_root="C:/repos/alpha")
    assert diagnostics["summary"]["matched_windows"] == 0
    assert diagnostics["summary"]["eligible_for_dispatch"] is False
    assert diagnostics["selection"]["reason_code"] == "no_matching_repo_window"
    guidance = diagnostics["operator_guidance"]
    assert guidance["issue"] == "no_matching_repo_window"
    assert guidance["deterministic_validation_path"]["recommended_path"] == "preflight_then_readiness_only"
    assert guidance["next_step"] == "open_or_restore_repo_window_and_rerun_preflight"
    failure_summary = diagnostics["targeting_failure_summary"]
    assert failure_summary["reason_class"] == "no_visible_repo_window_matches_aliases"
    assert failure_summary["visible_windows_total"] == 1
    assert failure_summary["visible_parsed_repo_counts"] == {"beta": 1}


def test_window_targeting_wrong_visible_window_id_gets_repo_specific_guidance(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - beta (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 302),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        window_id="hwnd:302",
    )

    assert diagnostics["selection"]["reason_code"] == "operator_window_id_not_found"
    guidance = diagnostics["operator_guidance"]
    assert guidance["issue"] == "operator_window_id_not_found"
    assert guidance["deterministic_validation_path"]["recommended_path"] == "preflight_then_readiness_only"
    failure_summary = diagnostics["targeting_failure_summary"]
    assert failure_summary["reason_class"] == "explicit_window_id_points_to_other_visible_repo"
    assert failure_summary["explicit_window_id"] == "hwnd:302"
    assert failure_summary["explicit_window_id_present_in_visible_snapshot"] is True
    assert failure_summary["explicit_window_id_matches_repo"] is False


def test_window_targeting_repo_mismatch_reasons(monkeypatch) -> None:
    windows = [
        _FakeWindow("Visual Studio Code", 401),
        _FakeWindow("Task A - gamma (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 402),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(repo_id="alpha", repo_root="C:/repos/alpha")
    assert diagnostics["summary"]["matched_windows"] == 0
    reasons = [reason for row in diagnostics["windows"] for reason in row.get("reasons", [])]
    assert "parsed_repo_missing" in reasons
    assert "alias_mismatch" in reasons


def test_dispatch_explicit_operator_selected_window_success(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 501),
        _FakeWindow("Task B - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 502),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.ensure_window_focus", lambda win, description="": True)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.send_text_to_chat", lambda win, text: True)

    result = dispatch_prompt_to_repo_window(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        prompt_text="run task",
        dry_run=False,
        window_id="hwnd:502",
    )
    assert result.success is True
    assert result.reason == "sent"
    assert result.selected_window_id == "hwnd:502"
    assert result.selected_window_title == "Task B - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code"
    assert result.diagnostics["selection"]["reason_code"] == "selected_by_operator_window_id"


def test_dispatch_readiness_blocks_not_foreground(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 601),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.ensure_window_focus", lambda win, description="": True)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot._probe_dispatch_readiness",
        lambda **kwargs: {
            "schema": "dispatch_readiness_v1",
            "mode": "operator_assisted",
            "target_window_id": "hwnd:601",
            "target_window_title": windows[0].Name,
            "target_hwnd": 601,
            "foreground": {
                "before": False,
                "after": False,
                "activation_attempted": False,
                "activation_succeeded": False,
            },
            "panel_detected": False,
            "input_detected": False,
            "send_button_detected": False,
            "active_sendable": False,
            "reason_code": "target_not_foreground",
            "summary": "blocked:target_not_foreground",
            "legacy_send_policy": {
                "enable_send_to_inactive_panels": False,
                "would_block_without_safe_mode": True,
            },
            "probe_error": None,
        },
    )

    result = dispatch_prompt_to_repo_window(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        prompt_text="run task",
        dry_run=False,
        window_id="hwnd:601",
        safe_activate=True,
    )

    assert result.success is False
    assert result.reason == "dispatch_not_ready"
    assert result.diagnostics["selection"]["reason_code"] == "target_not_foreground"
    assert result.diagnostics["dispatch_readiness"]["active_sendable"] is False


def test_dispatch_readiness_blocks_no_input(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 602),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.ensure_window_focus", lambda win, description="": True)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot._probe_dispatch_readiness",
        lambda **kwargs: {
            "schema": "dispatch_readiness_v1",
            "mode": "safe_activate",
            "target_window_id": "hwnd:602",
            "target_window_title": windows[0].Name,
            "target_hwnd": 602,
            "foreground": {
                "before": True,
                "after": True,
                "activation_attempted": False,
                "activation_succeeded": False,
            },
            "panel_detected": True,
            "input_detected": False,
            "send_button_detected": False,
            "active_sendable": False,
            "reason_code": "chat_input_not_detected",
            "summary": "blocked:chat_input_not_detected",
            "legacy_send_policy": {
                "enable_send_to_inactive_panels": False,
                "would_block_without_safe_mode": True,
            },
            "probe_error": None,
        },
    )

    result = dispatch_prompt_to_repo_window(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        prompt_text="run task",
        dry_run=False,
        window_id="hwnd:602",
        safe_activate=True,
    )

    assert result.success is False
    assert result.reason == "dispatch_not_ready"
    assert result.diagnostics["selection"]["reason_code"] == "chat_input_not_detected"
    assert result.diagnostics["dispatch_readiness"]["input_detected"] is False


def test_dispatch_readiness_safe_activate_success(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 603),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.ensure_window_focus", lambda win, description="": True)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot._probe_dispatch_readiness",
        lambda **kwargs: {
            "schema": "dispatch_readiness_v1",
            "mode": "safe_activate",
            "target_window_id": "hwnd:603",
            "target_window_title": windows[0].Name,
            "target_hwnd": 603,
            "foreground": {
                "before": True,
                "after": True,
                "activation_attempted": False,
                "activation_succeeded": False,
            },
            "panel_detected": True,
            "input_detected": True,
            "send_button_detected": True,
            "active_sendable": True,
            "reason_code": "ready_to_send",
            "summary": "ready",
            "legacy_send_policy": {
                "enable_send_to_inactive_panels": False,
                "would_block_without_safe_mode": True,
            },
            "probe_error": None,
        },
    )
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot._send_text_to_active_chat", lambda *args, **kwargs: (True, "sent"))

    result = dispatch_prompt_to_repo_window(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        prompt_text="run task",
        dry_run=False,
        window_id="hwnd:603",
        safe_activate=True,
    )

    assert result.success is True
    assert result.reason == "sent"
    assert result.diagnostics["dispatch_readiness"]["reason_code"] == "ready_to_send"
    assert result.diagnostics["dispatch_readiness"]["active_sendable"] is True


def test_preflight_window_diagnostics_include_win32_visibility(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 7001),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot.enumerate_vscode_windows_win32",
        lambda: {
            "summary": {"vscode_title_matches": 1},
            "windows": [
                {
                    "window_id": "hwnd:7001",
                    "hwnd": 7001,
                    "title": "Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code",
                    "class_name": "Chrome_WidgetWin_1",
                    "is_vscode_title_match": True,
                    "is_visible": True,
                    "is_minimized": False,
                    "is_cloaked": False,
                    "cloaked_raw": 0,
                    "inclusion_reason": "included_vscode_visible",
                }
            ],
        },
    )

    preflight = build_window_preflight(repo_targets=[("alpha", "C:/repos/alpha")], timeout=0.2)
    discovered = preflight["windows_discovered"][0]
    assert discovered["is_visible"] is True
    assert discovered["is_minimized"] is False
    assert discovered["is_cloaked"] is False
    assert discovered["inclusion_reason"] == "included_by_uia"
    assert preflight["summary"]["windows_omitted_from_uia"] == 0


def test_preflight_reports_cloaked_windows_omitted_from_uia(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 7101),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot.enumerate_vscode_windows_win32",
        lambda: {
            "summary": {"vscode_title_matches": 2, "vscode_cloaked": 1},
            "windows": [
                {
                    "window_id": "hwnd:7101",
                    "hwnd": 7101,
                    "title": "Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code",
                    "class_name": "Chrome_WidgetWin_1",
                    "is_vscode_title_match": True,
                    "is_visible": True,
                    "is_minimized": False,
                    "is_cloaked": False,
                    "cloaked_raw": 0,
                    "inclusion_reason": "included_vscode_visible",
                },
                {
                    "window_id": "hwnd:7999",
                    "hwnd": 7999,
                    "title": "Task X - tf (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code",
                    "class_name": "Chrome_WidgetWin_1",
                    "is_vscode_title_match": True,
                    "is_visible": False,
                    "is_minimized": False,
                    "is_cloaked": True,
                    "cloaked_raw": 1,
                    "inclusion_reason": "included_vscode_cloaked_possible_off_desktop",
                },
            ],
        },
    )

    preflight = build_window_preflight(repo_targets=[("alpha", "C:/repos/alpha")], timeout=0.2)
    enum_diag = preflight["window_enumeration_diagnostics"]
    omitted = enum_diag["windows_omitted_from_uia"]
    assert len(omitted) == 1
    assert omitted[0]["window_id"] == "hwnd:7999"
    assert omitted[0]["is_cloaked"] is True
    assert preflight["summary"]["windows_omitted_from_uia"] == 1


def test_fallback_request_construction_open_then_ready(monkeypatch) -> None:
    preflight_before = {
        "repo_diagnostics": [
            {
                "summary": {"eligible_for_dispatch": False},
                "selection": {"reason_code": "no_matching_repo_window"},
            }
        ]
    }
    preflight_after = {
        "repo_diagnostics": [
            {
                "summary": {"eligible_for_dispatch": True},
                "selection": {
                    "reason_code": "selected_single_match",
                    "selected_window_id": "hwnd:8801",
                    "selected_window_title": "Chat - alpha (Workspace) - Visual Studio Code",
                },
            }
        ]
    }
    calls = {"count": 0, "open": None}

    def _fake_preflight(**kwargs):
        calls["count"] += 1
        return preflight_before if calls["count"] == 1 else preflight_after

    def _fake_popen(command, cwd=None):
        calls["open"] = {"command": list(command), "cwd": cwd}
        return object()

    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.build_window_preflight", _fake_preflight)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot._find_code_cli", lambda: "code.cmd")
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.subprocess.Popen", _fake_popen)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.time.sleep", lambda _seconds: None)

    workspace_path = str((Path.cwd() / "tests").resolve())
    diag = prepare_explicit_fallback_targeting(
        repo_id="alpha",
        repo_root=workspace_path,
        workspace_path=workspace_path,
        open_if_missing=True,
        open_wait_seconds=0.01,
    )

    assert diag["dispatch_allowed"] is True
    assert diag["reason"] == "fallback_ready_after_open"
    assert diag["open_attempted"] is True
    assert calls["open"] is not None
    assert calls["open"]["command"][0] == "code.cmd"
    assert calls["open"]["command"][1] == "-n"
    assert calls["open"]["command"][2] == workspace_path


def test_fallback_does_not_open_for_ambiguous_selection(monkeypatch) -> None:
    preflight_ambiguous = {
        "repo_diagnostics": [
            {
                "summary": {"eligible_for_dispatch": False},
                "selection": {"reason_code": "ambiguous_repo_window"},
            }
        ]
    }

    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.build_window_preflight", lambda **kwargs: preflight_ambiguous)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot._find_code_cli", lambda: "code.cmd")

    workspace_path = str((Path.cwd() / "tests").resolve())
    diag = prepare_explicit_fallback_targeting(
        repo_id="alpha",
        repo_root=workspace_path,
        workspace_path=workspace_path,
        open_if_missing=True,
    )

    assert diag["dispatch_allowed"] is False
    assert diag["reason"] == "ambiguous_repo_window"
    assert diag["open_attempted"] is False


def test_window_targeting_rejects_protected_self_repo_context(monkeypatch) -> None:
    windows = [
        _FakeWindow("Chat - desktop-agent-automation (Workspace) - Visual Studio Code", 9901),
        _FakeWindow("Task A - alpha (Workspace) - Visual Studio Code", 9902),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)

    diagnostics = inspect_repo_window_targeting(repo_id="alpha", repo_root="C:/repos/alpha")
    protected = next(row for row in diagnostics["windows"] if row["window_id"] == "hwnd:9901")
    assert protected["dispatch_eligible"] is False
    assert "protected_repo_context_rejected" in (protected.get("reasons") or [])
    assert diagnostics["summary"]["matched_windows"] == 1


def test_fallback_success_without_open_when_preflight_ready(monkeypatch) -> None:
    preflight_ready = {
        "repo_diagnostics": [
            {
                "summary": {"eligible_for_dispatch": True},
                "selection": {
                    "reason_code": "selected_by_operator_window_id",
                    "selected_window_id": "hwnd:7777",
                    "selected_window_title": "Task - alpha (Workspace) - Visual Studio Code",
                },
            }
        ]
    }

    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.build_window_preflight", lambda **kwargs: preflight_ready)

    workspace_path = str((Path.cwd() / "tests").resolve())
    diag = prepare_explicit_fallback_targeting(
        repo_id="alpha",
        repo_root=workspace_path,
        workspace_path=workspace_path,
        window_id="hwnd:7777",
        open_if_missing=False,
    )

    assert diag["dispatch_allowed"] is True
    assert diag["reason"] == "preflight_ready"
    assert diag["selected_window_id"] == "hwnd:7777"
    assert diag["open_attempted"] is False


def test_dispatch_dry_run_does_not_focus_window(monkeypatch) -> None:
    windows = [
        _FakeWindow("Task A - alpha (Workspace) [WSL: Ubuntu-24.04] - Visual Studio Code", 1501),
    ]
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.find_all_vscode_windows", lambda timeout=0.5: windows)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot.enumerate_vscode_windows_win32",
        lambda: {
            "summary": {"vscode_title_matches": 1},
            "windows": [
                {
                    "window_id": "hwnd:1501",
                    "hwnd": 1501,
                    "title": windows[0].Name,
                    "class_name": "Chrome_WidgetWin_1",
                    "is_vscode_title_match": True,
                    "is_visible": True,
                    "is_minimized": False,
                    "is_cloaked": False,
                    "cloaked_raw": 0,
                    "inclusion_reason": "included_vscode_visible",
                }
            ],
        },
    )

    def _unexpected_focus(*args, **kwargs):
        raise AssertionError("dry-run should not focus the target window")

    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.ensure_window_focus", _unexpected_focus)

    result = dispatch_prompt_to_repo_window(
        repo_id="alpha",
        repo_root="C:/repos/alpha",
        prompt_text="run task",
        dry_run=True,
    )

    assert result.success is True
    assert result.reason == "dry_run"
    assert result.selected_window_id == "hwnd:1501"


def test_probe_dispatch_readiness_emits_foreground_block_guidance(monkeypatch) -> None:
    target = _FakeWindow("Chat - alpha (Workspace) - Visual Studio Code", 601)

    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot._is_target_foreground", lambda hwnd: False)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.ensure_window_focus", lambda win, description="": True)
    monkeypatch.setattr(
        "automation.orchestration_v1.vscode_pilot.collect_window_snapshot",
        lambda timeout=0.2: [
            {
                "window_id": "hwnd:999",
                "title": "Other app window",
                "dispatch_reference": None,
            }
        ],
    )
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_foreground_window", lambda: 999)
    monkeypatch.setattr("automation.orchestration_v1.vscode_pilot.get_root_window", lambda hwnd: hwnd)

    from automation.orchestration_v1 import vscode_pilot

    readiness = vscode_pilot._probe_dispatch_readiness(
        target_win=target,
        selected_window_id="hwnd:601",
        selected_window_title=target.Name,
        safe_activate=True,
    )

    assert readiness["reason_code"] == "target_not_foreground"
    assert readiness["active_sendable"] is False
    assert readiness["foreground"]["activation_attempted"] is True
    guidance = readiness["operator_guidance"]
    assert isinstance(guidance, dict)
    assert guidance["issue"] == "target_not_foreground"
    assert guidance["selected_window"]["window_id"] == "hwnd:601"
    assert guidance["foreground_window"]["foreground_window_id"] == "hwnd:999"
    assert len(guidance["recommended_actions"]) == 4
