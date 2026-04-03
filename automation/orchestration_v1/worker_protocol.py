from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Dict, List, Optional

from automation.orchestration_v1.models import (
    ChangedFile,
    ManagedRepoConfig,
    ValidationRun,
    WorkerCompletionReport,
    WorkerOutcome,
    WorkItem,
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
        "status: success | partial | blocked | failed\n"
        "summary: ...\n"
        "files_changed:\n"
        "  - path: ...\n"
        "    reason: ...\n"
        "validation_run:\n"
        "  - command: ...\n"
        "    result: pass | fail | not_run\n"
        "    notes: ...\n"
        "blockers:\n"
        "  - ...\n"
        "risks:\n"
        "  - ...\n"
        "next_recommended_actions:\n"
        "  - ...\n"
        "handover_written_to: ...\n"
    )


def parse_worker_completion_report(raw_text: str) -> Optional[WorkerCompletionReport]:
    if not raw_text or not raw_text.strip():
        return None

    parsed_json = _try_parse_json(raw_text)
    if parsed_json is not None:
        return _from_mapping(parsed_json, raw_text)

    status_match = re.search(r"(?im)^status\s*:\s*(success|partial|blocked|failed)\s*$", raw_text)
    summary_match = re.search(r"(?im)^summary\s*:\s*(.+)$", raw_text)
    if not status_match:
        return None

    status = WorkerOutcome(status_match.group(1).lower())
    summary = summary_match.group(1).strip() if summary_match else ""

    files_changed = _extract_file_rows(raw_text)
    validations = _extract_validation_rows(raw_text)
    blockers = _extract_simple_list(raw_text, "blockers")
    risks = _extract_simple_list(raw_text, "risks")
    next_actions = _extract_simple_list(raw_text, "next_recommended_actions")
    handover_match = re.search(r"(?im)^handover_written_to\s*:\s*(.+)$", raw_text)

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
    status_raw = str(payload.get("status", "")).strip().lower()
    if status_raw not in {"success", "partial", "blocked", "failed"}:
        return None

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

    return WorkerCompletionReport(
        status=WorkerOutcome(status_raw),
        summary=str(payload.get("summary", "")).strip(),
        files_changed=files_changed,
        tests_validation_run=validations,
        blockers=[str(x).strip() for x in payload.get("blockers", [])] if isinstance(payload.get("blockers"), list) else [],
        risks=[str(x).strip() for x in payload.get("risks", [])] if isinstance(payload.get("risks"), list) else [],
        next_recommended_actions=[str(x).strip() for x in payload.get("next_recommended_actions", [])]
        if isinstance(payload.get("next_recommended_actions"), list)
        else [],
        handover_report_path=str(payload.get("handover_written_to", "")).strip() or None,
        raw_text=raw_text,
    )


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
