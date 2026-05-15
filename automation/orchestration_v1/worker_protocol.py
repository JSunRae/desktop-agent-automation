from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from automation.orchestration_v1.models import (
    ChangedFile,
    ManagedRepoConfig,
    ValidationRun,
    WorkerCompletionReport,
    WorkerOutcome,
    WorkItem,
)

STRICT_PROTOCOL = "pilot_response_v1"
STRICT_START_TEMPLATE = "[[DAA_PILOT_RESPONSE_V1|START|run_id={run_id}|repo_id={repo_id}]]"
STRICT_END_TEMPLATE = "[[DAA_PILOT_RESPONSE_V1|END|run_id={run_id}|repo_id={repo_id}]]"
STRICT_START_RE = re.compile(
    r"^\[\[DAA_PILOT_RESPONSE_V1\|START\|run_id=([^|\]]+)\|repo_id=([^|\]]+)\]\]$",
    re.MULTILINE,
)
STRICT_END_RE = re.compile(
    r"^\[\[DAA_PILOT_RESPONSE_V1\|END\|run_id=([^|\]]+)\|repo_id=([^|\]]+)\]\]$",
    re.MULTILINE,
)


def _preview_text(text: str, *, limit: int = 120) -> str:
    collapsed = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 3)] + "..."


def strict_markers(*, run_id: str, repo_id: str) -> Tuple[str, str]:
    return (
        STRICT_START_TEMPLATE.format(run_id=run_id, repo_id=repo_id),
        STRICT_END_TEMPLATE.format(run_id=run_id, repo_id=repo_id),
    )


def compose_worker_prompt(
    *,
    run_id: str,
    work_item: WorkItem,
    repo_config: ManagedRepoConfig,
    context_excerpt: str,
    reason_selected: str,
) -> str:
    constraints = "\n".join(f"- {item}" for item in work_item.constraints)
    validations = "\n".join(f"- {cmd}" for cmd in (work_item.suggested_validation or repo_config.validation_commands))

    strict_start, strict_end = strict_markers(run_id=run_id, repo_id=work_item.repo)

    strict_example_payload = {
        "protocol": STRICT_PROTOCOL,
        "run_id": run_id,
        "repo_id": work_item.repo,
        "status": "partial",
        "summary": "ACK: task received. Scoped triage complete.",
        "body": {
            "files_changed": [],
            "validation_run": [{"command": "not_run_in_first_reply", "result": "not_run", "notes": "triage_only"}],
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
        "handover_written_to": "",
    }

    return (
        f"You are the repo-local execution agent for repo: {work_item.repo}.\n\n"
        "You are coordinated by the desktop automation orchestrator. Execute one scoped task while respecting repo-local instructions and governance.\n\n"
        "Scope\n"
        f"Task id: {work_item.work_item_id}\n"
        f"Run id: {run_id}\n"
        f"Title: {work_item.title}\n"
        f"Objective: Complete this scoped task with minimal, auditable changes.\n\n"
        "Context supplied by orchestrator\n"
        f"Source: {work_item.source}\n"
        f"Reason selected: {reason_selected}\n"
        "Relevant constraints:\n"
        f"{constraints}\n\n"
        "Relevant files/areas:\n"
        "- Respect repo boundaries and local conventions.\n\n"
        "Relevant errors/tasks/handovers:\n"
        f"{context_excerpt[:2000]}\n\n"
        "Required validation\n"
        f"{validations}\n\n"
        "Required completion format\n"
        "STRICT PILOT RESPONSE CONTRACT (mandatory for pilot mode)\n"
        "Output must contain exactly 3 blocks only: START marker line, one JSON object, END marker line.\n"
        "Do not include markdown code fences, headings, commentary, or any text outside the markers.\n"
        "Return your final completion wrapped by these exact markers:\n"
        f"{strict_start}\n"
        "<JSON payload body only>\n"
        f"{strict_end}\n\n"
        "Required JSON payload schema (final reply must be JSON, not YAML):\n"
        "{\n"
        '  "protocol": "pilot_response_v1",\n'
        f'  "run_id": "{run_id}",\n'
        f'  "repo_id": "{work_item.repo}",\n'
        '  "status": "success|partial|blocked|failed",\n'
        '  "summary": "...",\n'
        '  "body": {\n'
        '    "files_changed": [{"path": "...", "reason": "..."}],\n'
        '    "validation_run": [{"command": "...", "result": "pass|fail|not_run", "notes": "..."}],\n'
        '    "blockers": ["..."],\n'
        '    "risks": ["..."],\n'
        '    "next_recommended_actions": ["..."]\n'
        '  },\n'
        '  "handover_written_to": "..."\n'
        "}\n\n"
        "Minimal known-good strict example (copy and update ids/status/summary):\n"
        f"{strict_start}\n"
        f"{json.dumps(strict_example_payload, separators=(',', ':'))}\n"
        f"{strict_end}\n"
    )


def parse_worker_completion_report_strict(
    *,
    raw_text: str,
    expected_run_id: str,
    expected_repo_id: str,
    source_channel: str,
) -> tuple[Optional[WorkerCompletionReport], Optional[str], Optional[Dict[str, Any]]]:
    def _fail(code: str, **meta: Any) -> tuple[None, str, Dict[str, Any]]:
        return None, code, meta

    if source_channel not in {"report_file", "panel_markers"}:
        return _fail("E_SOURCE_UNSUPPORTED", source_channel=source_channel)

    if not raw_text or not raw_text.strip():
        return _fail("E_EMPTY_RESPONSE", raw_len=len(raw_text or ""))

    start_matches = list(STRICT_START_RE.finditer(raw_text))
    end_matches = list(STRICT_END_RE.finditer(raw_text))
    if len(start_matches) != 1:
        return _fail(
            "E_MARKER_START_INVALID",
            start_marker_count=len(start_matches),
            end_marker_count=len(end_matches),
            expected_start_marker=STRICT_START_TEMPLATE.format(run_id=expected_run_id, repo_id=expected_repo_id),
        )
    if len(end_matches) != 1:
        return _fail(
            "E_MARKER_END_INVALID",
            start_marker_count=len(start_matches),
            end_marker_count=len(end_matches),
            expected_end_marker=STRICT_END_TEMPLATE.format(run_id=expected_run_id, repo_id=expected_repo_id),
        )

    start = start_matches[0]
    end = end_matches[0]
    if end.start() <= start.end():
        return _fail("E_MARKER_ORDER_INVALID", start_marker_index=start.start(), end_marker_index=end.start())

    marker_run_id = start.group(1).strip()
    marker_repo_id = start.group(2).strip()
    end_run_id = end.group(1).strip()
    end_repo_id = end.group(2).strip()
    if marker_run_id != end_run_id or marker_repo_id != end_repo_id:
        return _fail(
            "E_MARKER_ID_MISMATCH",
            start_run_id=marker_run_id,
            start_repo_id=marker_repo_id,
            end_run_id=end_run_id,
            end_repo_id=end_repo_id,
        )
    if marker_run_id != expected_run_id:
        return _fail("E_RUN_ID_MISMATCH", expected_run_id=expected_run_id, actual_run_id=marker_run_id)
    if marker_repo_id.lower() != expected_repo_id.lower():
        return _fail("E_REPO_ID_MISMATCH", expected_repo_id=expected_repo_id, actual_repo_id=marker_repo_id)

    outside = (raw_text[: start.start()] + raw_text[end.end() :]).strip()
    if outside:
        return _fail(
            "E_OUTSIDE_MARKER_TEXT",
            outside_text_len=len(outside),
            outside_text_preview=_preview_text(outside),
        )

    payload_text = raw_text[start.end() : end.start()].strip()
    if not payload_text:
        return _fail("E_PAYLOAD_EMPTY", payload_len=0)

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        return _fail(
            "E_PAYLOAD_NOT_JSON",
            payload_len=len(payload_text),
            json_error=str(exc),
            json_error_pos=exc.pos,
            json_error_lineno=exc.lineno,
            json_error_colno=exc.colno,
            payload_preview=_preview_text(payload_text),
        )
    if not isinstance(payload, dict):
        return _fail("E_PAYLOAD_NOT_OBJECT", payload_type=type(payload).__name__)

    protocol = str(payload.get("protocol", "")).strip()
    if protocol != STRICT_PROTOCOL:
        return _fail("E_PROTOCOL_UNSUPPORTED", expected_protocol=STRICT_PROTOCOL, actual_protocol=protocol)

    payload_run_id = str(payload.get("run_id", "")).strip()
    payload_repo_id = str(payload.get("repo_id", "")).strip()
    if payload_run_id != expected_run_id:
        return _fail("E_PAYLOAD_RUN_ID_MISMATCH", expected_run_id=expected_run_id, actual_run_id=payload_run_id)
    if payload_repo_id.lower() != expected_repo_id.lower():
        return _fail("E_PAYLOAD_REPO_ID_MISMATCH", expected_repo_id=expected_repo_id, actual_repo_id=payload_repo_id)

    status_raw = str(payload.get("status", "")).strip().lower()
    if status_raw not in {"success", "partial", "blocked", "failed"}:
        return _fail("E_STATUS_INVALID", actual_status=status_raw)
    status = WorkerOutcome(status_raw)

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return _fail("E_SUMMARY_INVALID", summary_type=type(summary).__name__)

    body = payload.get("body")
    if not isinstance(body, dict):
        return _fail("E_BODY_MISSING", body_type=type(body).__name__)

    files_raw = body.get("files_changed", [])
    validations_raw = body.get("validation_run", [])
    blockers_raw = body.get("blockers", [])
    risks_raw = body.get("risks", [])
    actions_raw = body.get("next_recommended_actions", [])

    if not isinstance(files_raw, list):
        return _fail("E_FILES_CHANGED_INVALID", files_type=type(files_raw).__name__)
    if not isinstance(validations_raw, list):
        return _fail("E_VALIDATION_RUN_INVALID", validation_type=type(validations_raw).__name__)
    if not isinstance(blockers_raw, list):
        return _fail("E_BLOCKERS_INVALID", blockers_type=type(blockers_raw).__name__)
    if not isinstance(risks_raw, list):
        return _fail("E_RISKS_INVALID", risks_type=type(risks_raw).__name__)
    if not isinstance(actions_raw, list):
        return _fail("E_NEXT_ACTIONS_INVALID", actions_type=type(actions_raw).__name__)

    files_changed: List[ChangedFile] = []
    for row in files_raw:
        if not isinstance(row, dict):
            return _fail("E_FILE_ROW_INVALID", row_type=type(row).__name__)
        path = str(row.get("path", "")).strip()
        reason = str(row.get("reason", "")).strip()
        if not path:
            return _fail("E_FILE_PATH_MISSING")
        files_changed.append(ChangedFile(path=path, reason=reason))

    validations: List[ValidationRun] = []
    for row in validations_raw:
        if not isinstance(row, dict):
            return _fail("E_VALIDATION_ROW_INVALID", row_type=type(row).__name__)
        command = str(row.get("command", "")).strip()
        result = str(row.get("result", "")).strip().lower()
        notes = str(row.get("notes", "")).strip()
        if result not in {"pass", "fail", "not_run"}:
            return _fail("E_VALIDATION_RESULT_INVALID", actual_result=result, command=command)
        validations.append(ValidationRun(command=command, result=result, notes=notes))

    blockers = [str(x).strip() for x in blockers_raw if str(x).strip()]
    risks = [str(x).strip() for x in risks_raw if str(x).strip()]
    next_actions = [str(x).strip() for x in actions_raw if str(x).strip()]

    report = WorkerCompletionReport(
        status=status,
        summary=summary.strip(),
        files_changed=files_changed,
        tests_validation_run=validations,
        blockers=blockers,
        risks=risks,
        next_recommended_actions=next_actions,
        handover_report_path=str(payload.get("handover_written_to", "")).strip() or None,
        raw_text=raw_text,
    )
    meta = {
        "channel": source_channel,
        "parse_mode": "strict_marked_json",
        "protocol": protocol,
    }
    return report, None, meta


def parse_worker_completion_report(raw_text: str) -> Optional[WorkerCompletionReport]:
    if not raw_text or not raw_text.strip():
        return None

    parsed_json = _try_parse_json(raw_text)
    if parsed_json is not None:
        parsed = _from_mapping(parsed_json, raw_text)
        if parsed is not None:
            return parsed

    status_match = re.search(r"(?im)^status\s*:\s*(.+?)\s*$", raw_text)
    summary_match = re.search(r"(?im)^summary\s*:\s*(.+)$", raw_text)
    status = _normalize_status(status_match.group(1).strip() if status_match else "")
    summary = summary_match.group(1).strip() if summary_match else ""

    files_changed = _extract_file_rows(raw_text)
    validations = _extract_validation_rows(raw_text)
    blockers = _extract_simple_list(raw_text, "blockers")
    risks = _extract_simple_list(raw_text, "risks")
    next_actions = _extract_simple_list(raw_text, "next_recommended_actions")
    handover_match = re.search(r"(?im)^handover_written_to\s*:\s*(.+)$", raw_text)

    if status is None:
        status = _infer_status(blockers=blockers, validations=validations, files_changed=files_changed, summary=summary)

    if status is None:
        return None

    return WorkerCompletionReport(
        status=status,
        summary=summary,
        files_changed=files_changed,
        tests_validation_run=validations,
        blockers=blockers,
        risks=risks,
        next_recommended_actions=next_actions,
        handover_report_path=handover_match.group(1).strip() if handover_match else None,
        raw_text=raw_text,
    )


def _try_parse_json(raw_text: str) -> Optional[Dict[str, object]]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _from_mapping(payload: Dict[str, object], raw_text: str) -> Optional[WorkerCompletionReport]:
    status = _normalize_status(str(payload.get("status", "")).strip())

    files_changed: List[ChangedFile] = []
    for row in payload.get("files_changed", []) if isinstance(payload.get("files_changed"), list) else []:
        if not isinstance(row, dict):
            continue
        files_changed.append(ChangedFile(path=str(row.get("path", "")).strip(), reason=str(row.get("reason", "")).strip()))

    validations: List[ValidationRun] = []
    validation_rows = payload.get("validation_run")
    if not isinstance(validation_rows, list):
        validation_rows = payload.get("tests_validation_run", [])
    if isinstance(validation_rows, list):
        for row in validation_rows:
            if not isinstance(row, dict):
                continue
            validations.append(
                ValidationRun(
                    command=str(row.get("command", "")).strip(),
                    result=str(row.get("result", "not_run")).strip(),
                    notes=str(row.get("notes", "")).strip(),
                )
            )

    summary = str(payload.get("summary", "")).strip()
    blockers = [str(x).strip() for x in payload.get("blockers", [])] if isinstance(payload.get("blockers"), list) else []
    risks = [str(x).strip() for x in payload.get("risks", [])] if isinstance(payload.get("risks"), list) else []
    next_actions = [str(x).strip() for x in payload.get("next_recommended_actions", [])] if isinstance(payload.get("next_recommended_actions"), list) else []

    if status is None:
        status = _infer_status(blockers=blockers, validations=validations, files_changed=files_changed, summary=summary)
    if status is None:
        return None

    return WorkerCompletionReport(
        status=status,
        summary=str(payload.get("summary", "")).strip(),
        files_changed=files_changed,
        tests_validation_run=validations,
        blockers=blockers,
        risks=risks,
        next_recommended_actions=next_actions,
        handover_report_path=str(payload.get("handover_written_to", "")).strip() or None,
        raw_text=raw_text,
    )


def _normalize_status(raw: str) -> Optional[WorkerOutcome]:
    value = (raw or "").strip().lower()
    if not value:
        return None
    aliases = {
        "success": WorkerOutcome.SUCCESS,
        "completed": WorkerOutcome.SUCCESS,
        "done": WorkerOutcome.SUCCESS,
        "ok": WorkerOutcome.SUCCESS,
        "partial": WorkerOutcome.PARTIAL,
        "partial_success": WorkerOutcome.PARTIAL,
        "incomplete": WorkerOutcome.PARTIAL,
        "needs_followup": WorkerOutcome.PARTIAL,
        "blocked": WorkerOutcome.BLOCKED,
        "waiting": WorkerOutcome.BLOCKED,
        "awaiting_input": WorkerOutcome.BLOCKED,
        "failed": WorkerOutcome.FAILED,
        "error": WorkerOutcome.FAILED,
        "exception": WorkerOutcome.FAILED,
        "aborted": WorkerOutcome.FAILED,
    }
    return aliases.get(value)


def _infer_status(
    *,
    blockers: List[str],
    validations: List[ValidationRun],
    files_changed: List[ChangedFile],
    summary: str,
) -> Optional[WorkerOutcome]:
    if blockers:
        return WorkerOutcome.BLOCKED
    if any(v.result.strip().lower() == "fail" for v in validations):
        return WorkerOutcome.FAILED
    if files_changed and summary:
        return WorkerOutcome.PARTIAL
    if summary:
        return WorkerOutcome.FAILED
    return None


def _extract_simple_list(raw_text: str, key: str) -> List[str]:
    lines = raw_text.splitlines()
    out: List[str] = []
    capture = False
    for line in lines:
        if re.match(rf"(?im)^\s*{re.escape(key)}\s*:\s*$", line):
            capture = True
            continue
        if capture and re.match(r"^\s*[a-zA-Z_]+\s*:\s*", line):
            break
        if capture:
            m = re.match(r"^\s*[-*]\s+(.+)\s*$", line)
            if m:
                out.append(m.group(1).strip())
    return out


def _extract_file_rows(raw_text: str) -> List[ChangedFile]:
    out: List[ChangedFile] = []
    path_matches = list(re.finditer(r"(?im)^\s*path\s*:\s*(.+)\s*$", raw_text))
    for path_match in path_matches:
        path = path_match.group(1).strip()
        reason_match = re.search(r"(?im)^\s*reason\s*:\s*(.+)\s*$", raw_text[path_match.end() : path_match.end() + 240])
        reason = reason_match.group(1).strip() if reason_match else ""
        out.append(ChangedFile(path=path, reason=reason))
    return out


def _extract_validation_rows(raw_text: str) -> List[ValidationRun]:
    out: List[ValidationRun] = []
    cmd_matches = list(re.finditer(r"(?im)^\s*command\s*:\s*(.+)\s*$", raw_text))
    for cmd_match in cmd_matches:
        segment = raw_text[cmd_match.end() : cmd_match.end() + 360]
        result_match = re.search(r"(?im)^\s*result\s*:\s*(pass|fail|not_run)\s*$", segment)
        notes_match = re.search(r"(?im)^\s*notes\s*:\s*(.+)\s*$", segment)
        out.append(
            ValidationRun(
                command=cmd_match.group(1).strip(),
                result=result_match.group(1).strip() if result_match else "not_run",
                notes=notes_match.group(1).strip() if notes_match else "",
            )
        )
    return out


def report_to_jsonable(report: WorkerCompletionReport) -> Dict[str, object]:
    payload = asdict(report)
    payload["status"] = report.status.value
    return payload
