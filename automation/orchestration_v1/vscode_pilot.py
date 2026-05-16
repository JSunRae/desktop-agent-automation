from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from automation.config import ENABLE_SEND_TO_INACTIVE_PANELS
from automation.orchestration_v1.models import WorkerCompletionReport, WorkerOutcome
from automation.orchestration_v1.worker_protocol import (
    parse_worker_completion_report,
    parse_worker_completion_report_strict,
)
from automation.panel_ui import (
    find_chat_editor_control,
    find_chat_input_box,
    find_send_button,
    get_panel_output_text,
    send_text_to_chat,
)
from automation.title_parsing import extract_repo_name_from_vscode_window_title
from automation.ui.button_clicker import ensure_window_focus
from automation.ui.vscode_windows import (
    enumerate_vscode_windows_win32,
    find_all_vscode_windows,
)
from automation.ui.window_utils import get_foreground_window, get_root_window

_STRICT_REJECTION_GUIDANCE: Dict[str, Dict[str, str]] = {
    "E_MARKER_START_INVALID": {
        "category": "framing_invalid",
        "hint_code": "missing_or_duplicate_start_marker",
        "hint_text": "Strict response must contain exactly one START marker line.",
        "operator_action": "Return only three blocks: one START marker line, one JSON object, and one END marker line.",
        "operator_next_step": "resend_clean_marker_framed_json",
    },
    "E_MARKER_END_INVALID": {
        "category": "framing_invalid",
        "hint_code": "missing_or_duplicate_end_marker",
        "hint_text": "Strict response must contain exactly one END marker line.",
        "operator_action": "Return only three blocks: one START marker line, one JSON object, and one END marker line.",
        "operator_next_step": "resend_clean_marker_framed_json",
    },
    "E_MARKER_ID_MISMATCH": {
        "category": "id_mismatch",
        "hint_code": "id_mismatch",
        "hint_text": "Markers were found, but the START and END marker IDs do not match each other.",
        "operator_action": "Copy the same run_id and repo_id into both marker lines before resending.",
        "operator_next_step": "resend_with_matching_marker_ids",
    },
    "E_RUN_ID_MISMATCH": {
        "category": "id_mismatch",
        "hint_code": "id_mismatch",
        "hint_text": "Marker run_id does not match the active orchestrator run.",
        "operator_action": "Copy the exact current run_id from the prompt into both markers and the JSON payload.",
        "operator_next_step": "resend_with_current_run_id",
    },
    "E_REPO_ID_MISMATCH": {
        "category": "id_mismatch",
        "hint_code": "id_mismatch",
        "hint_text": "Marker repo_id does not match the selected repository.",
        "operator_action": "Copy the exact current repo_id from the prompt into both markers and the JSON payload.",
        "operator_next_step": "resend_with_current_repo_id",
    },
    "E_PAYLOAD_RUN_ID_MISMATCH": {
        "category": "id_mismatch",
        "hint_code": "payload_run_id_mismatch",
        "hint_text": "JSON payload run_id does not match the active run or marker line.",
        "operator_action": "Update the payload run_id to match the current prompt and marker lines.",
        "operator_next_step": "resend_with_current_run_id",
    },
    "E_PAYLOAD_REPO_ID_MISMATCH": {
        "category": "id_mismatch",
        "hint_code": "payload_repo_id_mismatch",
        "hint_text": "JSON payload repo_id does not match the selected repository or marker line.",
        "operator_action": "Update the payload repo_id to match the current prompt and marker lines.",
        "operator_next_step": "resend_with_current_repo_id",
    },
    "E_MARKER_ORDER_INVALID": {
        "category": "framing_invalid",
        "hint_code": "marker_order_invalid",
        "hint_text": "Markers were detected, but their order is invalid.",
        "operator_action": "Place the START marker before the JSON body and the END marker after the JSON body.",
        "operator_next_step": "resend_clean_marker_framed_json",
    },
    "E_OUTSIDE_MARKER_TEXT": {
        "category": "framing_invalid",
        "hint_code": "outside_marker_text",
        "hint_text": "Strict payload has extra text outside the START/END markers.",
        "operator_action": "Remove headings, code fences, commentary, and trailing notes outside the markers.",
        "operator_next_step": "resend_clean_marker_framed_json",
    },
    "E_PAYLOAD_EMPTY": {
        "category": "payload_invalid",
        "hint_code": "payload_empty",
        "hint_text": "Markers were found, but the JSON body between them is empty.",
        "operator_action": "Insert exactly one JSON object between the START and END markers.",
        "operator_next_step": "resend_clean_marker_framed_json",
    },
    "E_PAYLOAD_NOT_JSON": {
        "category": "payload_invalid",
        "hint_code": "payload_not_json",
        "hint_text": "The content between the markers is not valid JSON.",
        "operator_action": "Return one valid JSON object only. Do not send YAML, quoted JSON, arrays, or fenced code blocks.",
        "operator_next_step": "resend_valid_json_object",
    },
    "E_PAYLOAD_NOT_OBJECT": {
        "category": "payload_invalid",
        "hint_code": "payload_not_object",
        "hint_text": "The content between the markers must be one JSON object.",
        "operator_action": "Wrap the payload as a single JSON object with protocol, run_id, repo_id, status, summary, and body fields.",
        "operator_next_step": "resend_valid_json_object",
    },
    "E_PROTOCOL_UNSUPPORTED": {
        "category": "protocol_mismatch",
        "hint_code": "protocol_mismatch",
        "hint_text": "Protocol field is present but not pilot_response_v1.",
        "operator_action": "Set protocol to pilot_response_v1 and resend the same marker-framed JSON object.",
        "operator_next_step": "resend_with_supported_protocol",
    },
    "E_STATUS_INVALID": {
        "category": "schema_invalid",
        "hint_code": "status_invalid",
        "hint_text": "Payload status must be one of success, partial, blocked, or failed.",
        "operator_action": "Use a valid status value and keep the rest of the payload unchanged.",
        "operator_next_step": "resend_with_valid_status",
    },
    "E_SUMMARY_INVALID": {
        "category": "schema_invalid",
        "hint_code": "summary_invalid",
        "hint_text": "Payload summary must be a non-empty string.",
        "operator_action": "Add a short non-empty summary string describing the current task outcome.",
        "operator_next_step": "resend_with_non_empty_summary",
    },
    "E_BODY_MISSING": {
        "category": "schema_invalid",
        "hint_code": "body_missing",
        "hint_text": "Payload body is missing or not an object.",
        "operator_action": "Provide a body object with files_changed, validation_run, blockers, risks, and next_recommended_actions arrays.",
        "operator_next_step": "resend_with_body_object",
    },
    "E_FILES_CHANGED_INVALID": {
        "category": "schema_invalid",
        "hint_code": "files_changed_invalid",
        "hint_text": "body.files_changed must be a JSON array.",
        "operator_action": "Set files_changed to an array of {path, reason} objects or an empty array.",
        "operator_next_step": "resend_with_valid_files_changed",
    },
    "E_VALIDATION_RUN_INVALID": {
        "category": "schema_invalid",
        "hint_code": "validation_run_invalid",
        "hint_text": "body.validation_run must be a JSON array.",
        "operator_action": "Set validation_run to an array of {command, result, notes} objects or an empty array.",
        "operator_next_step": "resend_with_valid_validation_run",
    },
    "E_FILE_ROW_INVALID": {
        "category": "schema_invalid",
        "hint_code": "file_row_invalid",
        "hint_text": "Each files_changed entry must be an object with at least a path field.",
        "operator_action": "Rewrite files_changed rows as JSON objects with path and optional reason fields.",
        "operator_next_step": "resend_with_valid_files_changed",
    },
    "E_VALIDATION_ROW_INVALID": {
        "category": "schema_invalid",
        "hint_code": "validation_row_invalid",
        "hint_text": "Each validation_run entry must be an object with command, result, and optional notes fields.",
        "operator_action": "Rewrite validation_run rows as JSON objects instead of strings or other scalar values.",
        "operator_next_step": "resend_with_valid_validation_run",
    },
    "E_VALIDATION_RESULT_INVALID": {
        "category": "schema_invalid",
        "hint_code": "validation_result_invalid",
        "hint_text": "A validation_run.result value is invalid.",
        "operator_action": "Use pass, fail, or not_run for each validation result value.",
        "operator_next_step": "resend_with_valid_validation_run",
    },
    "E_DUPLICATE_CANDIDATE": {
        "category": "candidate_conflict",
        "hint_code": "duplicate_candidate",
        "hint_text": "The same response candidate was seen more than once.",
        "operator_action": "Keep only one authoritative report for this run and remove duplicate copies if possible.",
        "operator_next_step": "deduplicate_worker_reports",
    },
    "E_CONFLICTING_CANDIDATE": {
        "category": "candidate_conflict",
        "hint_code": "conflicting_candidate",
        "hint_text": "Different strict responses were seen for the same run.",
        "operator_action": "Choose one authoritative response source and clear conflicting report copies before retrying.",
        "operator_next_step": "deduplicate_worker_reports",
    },
    "E_AMBIGUOUS_REPO_WINDOW": {
        "category": "targeting_invalid",
        "hint_code": "ambiguous_repo_window",
        "hint_text": "Multiple matching repo windows were found during panel fallback.",
        "operator_action": "Rerun preflight or readiness and specify --pilot-window-id before using panel fallback.",
        "operator_next_step": "rerun_with_explicit_window_id",
    },
    "E_SANDBOX_CHANNEL_NOT_ALLOWED": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_channel_not_allowed",
        "hint_text": "Sandbox self-test accepts report files only, not panel output.",
        "operator_action": "Write the strict sandbox reply to an allowed report file instead of relying on panel fallback.",
        "operator_next_step": "write_allowed_sandbox_report",
    },
    "E_SANDBOX_REPORT_PATH_MISSING": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_report_path_missing",
        "hint_text": "Sandbox self-test requires a concrete report path.",
        "operator_action": "Write the sandbox response to one of the allowed report file paths created by the self-test command.",
        "operator_next_step": "write_allowed_sandbox_report",
    },
    "E_SANDBOX_REPORT_PATH_NOT_ALLOWED": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_report_path_not_allowed",
        "hint_text": "Sandbox self-test report path is not on the allowlist.",
        "operator_action": "Write only to one of the allowed sandbox report paths printed by the self-test command.",
        "operator_next_step": "write_allowed_sandbox_report",
    },
    "E_SANDBOX_STATUS_NOT_TRIAGE": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_status_not_triage",
        "hint_text": "Sandbox self-test only accepts triage statuses partial or blocked.",
        "operator_action": "Use status partial or blocked for sandbox replies; do not claim success or failed completion in self-test mode.",
        "operator_next_step": "resend_sandbox_triage_only",
    },
    "E_SANDBOX_FILES_CHANGED": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_files_changed",
        "hint_text": "Sandbox self-test does not allow code or file edits.",
        "operator_action": "Set files_changed to an empty array for sandbox self-test responses.",
        "operator_next_step": "resend_sandbox_triage_only",
    },
    "E_SANDBOX_VALIDATION_REQUIRED": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_validation_required",
        "hint_text": "Sandbox self-test requires at least one validation_run entry marked not_run.",
        "operator_action": "Include a triage-only validation row such as not_run_in_first_reply with result not_run.",
        "operator_next_step": "resend_sandbox_triage_only",
    },
    "E_SANDBOX_VALIDATION_EXECUTED": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_validation_executed",
        "hint_text": "Sandbox self-test does not allow executed validations.",
        "operator_action": "Set every validation_run result to not_run for sandbox self-test responses.",
        "operator_next_step": "resend_sandbox_triage_only",
    },
    "E_SANDBOX_HANDOVER_NOT_ALLOWED": {
        "category": "sandbox_contract_invalid",
        "hint_code": "sandbox_handover_not_allowed",
        "hint_text": "Sandbox self-test does not allow handover output paths.",
        "operator_action": "Leave handover_written_to empty during sandbox self-test responses.",
        "operator_next_step": "resend_sandbox_triage_only",
    },
}

_PROTECTED_SELF_REPO = "desktop-agent-automation"


def _close_but_invalid_hint(reason: str) -> Optional[Dict[str, str]]:
    mapped = _STRICT_REJECTION_GUIDANCE.get(reason)
    if mapped is None:
        return None
    return {
        "hint_code": mapped["hint_code"],
        "hint_text": mapped["hint_text"],
    }


def _strict_rejection_guidance(reason: str, detail: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    mapped = _STRICT_REJECTION_GUIDANCE.get(reason)
    if mapped is None:
        return None
    guidance: Dict[str, Any] = {"reason": reason, **mapped}
    if reason == "E_PAYLOAD_NOT_JSON":
        line = (detail or {}).get("json_error_lineno")
        column = (detail or {}).get("json_error_colno")
        if isinstance(line, int) and isinstance(column, int):
            guidance["hint_text"] = f"The content between the markers is not valid JSON near line {line}, column {column}."
    elif reason == "E_MARKER_START_INVALID":
        count = (detail or {}).get("start_marker_count")
        if isinstance(count, int) and count > 1:
            guidance["hint_text"] = "Multiple START markers were found; strict mode requires exactly one START marker line."
    elif reason == "E_MARKER_END_INVALID":
        count = (detail or {}).get("end_marker_count")
        if isinstance(count, int) and count > 1:
            guidance["hint_text"] = "Multiple END markers were found; strict mode requires exactly one END marker line."
    return guidance


@dataclass
class PilotDispatchResult:
    success: bool
    reason: str
    repo_id: str
    matched_window_titles: List[str]
    selected_window_title: Optional[str]
    selected_window_id: Optional[str]
    diagnostics: Dict[str, Any]


@dataclass
class PilotResponsePollResult:
    report: Optional[WorkerCompletionReport]
    source: str
    report_path: Optional[str]
    parse_mode: Optional[str]
    elapsed_ms: int
    malformed_seen: bool
    response_diagnostics: Dict[str, Any]


def _normalize_repo_name(name: str) -> str:
    value = (name or "").strip().lower()
    value = re.sub(r"\s*\(workspace\)\s*$", "", value)
    return value


def _canonicalize_path(raw_path: Optional[str]) -> Optional[str]:
    text = str(raw_path or "").strip()
    if not text:
        return None
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except Exception:
        return None


def _find_code_cli() -> Optional[str]:
    env_override = os.environ.get("VSCODE_CLI")
    if env_override:
        return env_override
    for command in ("code.cmd", "code", "codium.cmd", "codium"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def _title_token_match(title: str, candidates: set[str]) -> Optional[str]:
    normalized_title = _normalize_repo_name(title)
    if not normalized_title:
        return None
    for candidate in sorted({item for item in candidates if item}, key=len, reverse=True):
        pattern = rf"(^|[\s\-\[\(]){re.escape(candidate)}($|[\s\-\]\)])"
        if re.search(pattern, normalized_title):
            return candidate
    return None


def _is_auxiliary_window_title(title: str) -> bool:
    normalized = (title or "").strip().lower()
    if not normalized:
        return False
    return (
        normalized.startswith("chat - ")
        or normalized.startswith("settings - ")
        or "127.0.0.1:" in normalized
        or "localhost:" in normalized
        or "/report/" in normalized
        or "/reports/" in normalized
    )


def _selection_rank_signature(row: Dict[str, Any]) -> Tuple[float, int, int]:
    visibility_score = 0
    if bool(row.get("is_visible")):
        visibility_score += 1
    if not bool(row.get("is_cloaked")):
        visibility_score += 1
    if not bool(row.get("is_minimized")):
        visibility_score += 1
    return (
        float(row.get("confidence") or 0.0),
        visibility_score,
        0 if bool(row.get("is_auxiliary_window")) else 1,
    )


def _selection_sort_key(row: Dict[str, Any]) -> Tuple[float, int, int, int, int, str, str]:
    confidence, visibility_score, non_auxiliary_score = _selection_rank_signature(row)
    foreground_score = 1 if bool(row.get("is_foreground")) else 0
    return (
        -confidence,
        -visibility_score,
        -non_auxiliary_score,
        -foreground_score,
        int(row.get("title_duplicate_count") or 0),
        str(row.get("title") or ""),
        str(row.get("window_id") or ""),
    )


def _evaluate_window_candidate(
    row: Dict[str, Any],
    *,
    repo_id: str,
    repo_root: Optional[str],
    aliases: set[str],
    current_foreground_id: Optional[str],
    dispatch_eligible_on_match: bool,
) -> Dict[str, Any]:
    evaluated = dict(row)
    title = str(evaluated.get("title", ""))
    parsed_repo = str(evaluated.get("parsed_repo", ""))
    normalized_parsed = _normalize_repo_name(parsed_repo)
    protected_title_match = _title_token_match(title, {_PROTECTED_SELF_REPO})
    if (normalized_parsed == _PROTECTED_SELF_REPO or protected_title_match == _PROTECTED_SELF_REPO) and _normalize_repo_name(repo_id) != _PROTECTED_SELF_REPO:
        evaluated["match_method"] = "protected_context_rejected"
        evaluated["confidence"] = 0.0
        evaluated["alias_match"] = False
        evaluated["match_candidate"] = False
        evaluated["reasons"] = ["protected_repo_context_rejected"]
        if str(evaluated.get("diagnostic_source") or "") == "win32_omitted":
            evaluated["reasons"].append("omitted_from_uia_snapshot")
        evaluated["dispatch_eligible"] = False
    else:
        method, confidence = _matching_method(
            parsed=parsed_repo,
            title=title,
            repo_id=repo_id,
            repo_root=repo_root,
            aliases=aliases,
        )
        alias_match = method != "no_match"
        reasons: List[str] = []
        if not parsed_repo:
            reasons.append("parsed_repo_missing")
        if alias_match:
            reasons.append("alias_match")
            if method == "title_token_exact":
                reasons.append("title_token_fallback")
        else:
            reasons.append("alias_mismatch")
        if str(evaluated.get("diagnostic_source") or "") == "win32_omitted":
            reasons.append("omitted_from_uia_snapshot")
        evaluated["match_method"] = method
        evaluated["confidence"] = confidence
        evaluated["alias_match"] = alias_match
        evaluated["match_candidate"] = alias_match
        evaluated["reasons"] = reasons
        evaluated["dispatch_eligible"] = bool(
            alias_match and dispatch_eligible_on_match and evaluated.get("dispatch_reference") is not None
        )

    evaluated["is_foreground"] = bool(str(evaluated.get("window_id", "")) == str(current_foreground_id))
    evaluated["is_auxiliary_window"] = _is_auxiliary_window_title(title)
    return evaluated


def prepare_explicit_fallback_targeting(
    *,
    repo_id: str,
    repo_root: Optional[str],
    workspace_path: str,
    window_index: Optional[int] = None,
    window_id: Optional[str] = None,
    preflight_timeout: float = 0.5,
    open_if_missing: bool = False,
    open_wait_seconds: float = 2.0,
) -> Dict[str, Any]:
    repo_key = _normalize_repo_name(repo_id)
    expected_root = _canonicalize_path(repo_root)
    requested_root = _canonicalize_path(workspace_path)
    diagnostics: Dict[str, Any] = {
        "mode": "explicit_repo_targeting_fallback_v1",
        "repo_id": repo_id,
        "repo_root": repo_root,
        "requested_workspace_path": workspace_path,
        "expected_workspace_path": expected_root,
        "canonical_workspace_path": requested_root,
        "path_match_exact": bool(expected_root and requested_root and expected_root == requested_root),
        "open_if_missing": bool(open_if_missing),
        "open_wait_seconds": float(max(0.0, open_wait_seconds)),
        "open_attempted": False,
        "open_command": None,
        "selected_window_id": None,
        "selected_window_title": None,
        "reason": "unknown",
        "dispatch_allowed": False,
    }

    if not workspace_path:
        diagnostics["reason"] = "fallback_workspace_path_missing"
        return diagnostics
    raw_requested = str(workspace_path).strip()
    if not Path(raw_requested).is_absolute():
        diagnostics["reason"] = "fallback_workspace_path_not_absolute"
        return diagnostics
    if not expected_root or not requested_root:
        diagnostics["reason"] = "fallback_workspace_path_invalid"
        return diagnostics
    if expected_root != requested_root:
        diagnostics["reason"] = "fallback_workspace_path_mismatch"
        return diagnostics

    idx_by_repo = {repo_key: window_index} if window_index is not None else {}
    id_by_repo = {repo_key: str(window_id).strip()} if str(window_id or "").strip() else {}
    before = build_window_preflight(
        repo_targets=[(repo_id, repo_root)],
        window_index_by_repo=idx_by_repo,
        window_id_by_repo=id_by_repo,
        timeout=max(0.1, float(preflight_timeout)),
    )
    diagnostics["preflight_before"] = before

    repo_diag = (before.get("repo_diagnostics") or [None])[0]
    summary = repo_diag.get("summary", {}) if isinstance(repo_diag, dict) else {}
    selection = repo_diag.get("selection", {}) if isinstance(repo_diag, dict) else {}
    if bool(summary.get("eligible_for_dispatch")):
        diagnostics["reason"] = "preflight_ready"
        diagnostics["dispatch_allowed"] = True
        diagnostics["selected_window_id"] = selection.get("selected_window_id")
        diagnostics["selected_window_title"] = selection.get("selected_window_title")
        return diagnostics

    selection_reason = str(selection.get("reason_code") or "fallback_preflight_not_ready")
    diagnostics["selected_window_id"] = selection.get("selected_window_id")
    diagnostics["selected_window_title"] = selection.get("selected_window_title")

    if not open_if_missing:
        diagnostics["reason"] = selection_reason
        return diagnostics

    if selection_reason not in {"no_matching_repo_window", "repo_window_detected_win32_only"}:
        diagnostics["reason"] = selection_reason
        return diagnostics

    code_cli = _find_code_cli()
    if not code_cli:
        diagnostics["reason"] = "fallback_code_cli_not_found"
        return diagnostics

    command = [code_cli, "-n", requested_root]
    diagnostics["open_attempted"] = True
    diagnostics["open_command"] = command
    try:
        subprocess.Popen(command, cwd=requested_root)
    except Exception as exc:
        diagnostics["reason"] = "fallback_open_workspace_failed"
        diagnostics["open_error"] = str(exc)
        return diagnostics

    wait_seconds = max(0.0, float(open_wait_seconds))
    if wait_seconds > 0.0:
        time.sleep(wait_seconds)

    after = build_window_preflight(
        repo_targets=[(repo_id, repo_root)],
        window_index_by_repo=idx_by_repo,
        window_id_by_repo=id_by_repo,
        timeout=max(0.1, float(preflight_timeout)),
    )
    diagnostics["preflight_after"] = after
    repo_diag_after = (after.get("repo_diagnostics") or [None])[0]
    summary_after = repo_diag_after.get("summary", {}) if isinstance(repo_diag_after, dict) else {}
    selection_after = repo_diag_after.get("selection", {}) if isinstance(repo_diag_after, dict) else {}
    diagnostics["selected_window_id"] = selection_after.get("selected_window_id")
    diagnostics["selected_window_title"] = selection_after.get("selected_window_title")

    if bool(summary_after.get("eligible_for_dispatch")):
        diagnostics["reason"] = "fallback_ready_after_open"
        diagnostics["dispatch_allowed"] = True
        return diagnostics

    diagnostics["reason"] = str(selection_after.get("reason_code") or "fallback_preflight_after_open_not_ready")
    return diagnostics


def _repo_aliases(repo_id: str, repo_root: Optional[str]) -> set[str]:
    aliases = {_normalize_repo_name(repo_id)}
    root = (repo_root or "").strip()
    if root:
        aliases.add(_normalize_repo_name(Path(root).name))
    if _normalize_repo_name(repo_id) == "trading":
        aliases.add("trading-system")
    return {x for x in aliases if x}


def _window_id(win: object, fallback_index: int) -> str:
    handle = getattr(win, "NativeWindowHandle", None)
    if isinstance(handle, int) and handle > 0:
        return f"hwnd:{handle}"
    return f"idx:{fallback_index}"


def _matching_method(
    *,
    parsed: str,
    title: str,
    repo_id: str,
    repo_root: Optional[str],
    aliases: set[str],
) -> Tuple[str, float]:
    normalized_parsed = _normalize_repo_name(parsed)
    normalized_repo = _normalize_repo_name(repo_id)
    root_name = _normalize_repo_name(Path(repo_root).name) if (repo_root or "").strip() else ""
    if normalized_parsed and normalized_parsed == normalized_repo:
        return "repo_id_exact", 0.95
    if normalized_parsed and root_name and normalized_parsed == root_name:
        return "root_basename_exact", 1.0
    if normalized_parsed and normalized_parsed in aliases:
        return "alias_exact", 0.85
    if not normalized_parsed and _title_token_match(title, aliases):
        return "title_token_exact", 0.4
    return "no_match", 0.0


def _build_preflight_command(*args: str) -> str:
    command = ["python", r"scripts\orchestration_v1.py"]
    command.extend(str(arg).strip() for arg in args if str(arg).strip())
    return " ".join(command)


def _build_supported_validation_path(*, repo_id: str, window_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": "pilot_validation_path_v1",
        "recommended_path": "preflight_then_readiness_only",
        "repo_id": repo_id,
        "note": (
            "Deterministic repo/window validation is preflight followed by readiness-only. "
            "Repo-targeted live dry-run is available as a targeting-only rehearsal before scheduler selection."
        ),
        "preflight_command": _build_preflight_command(
            "--pilot-preflight",
            "--pilot-preflight-repo",
            repo_id,
            "--json",
        ),
    }
    normalized_window_id = str(window_id or "").strip()
    if normalized_window_id:
        payload["window_id"] = normalized_window_id
        payload["readiness_command"] = _build_preflight_command(
            "--pilot-readiness-only",
            "--pilot-readiness-repo",
            repo_id,
            "--pilot-window-id",
            normalized_window_id,
            "--json",
        )
        payload["repo_targeted_dry_run_command"] = _build_preflight_command(
            "--pilot-live-dispatch",
            "--pilot-dry-run",
            "--pilot-dry-run-repo",
            repo_id,
            "--pilot-window-id",
            normalized_window_id,
            "--json",
        )
    return payload


def _build_targeting_failure_summary(
    *,
    repo_id: str,
    aliases: set[str],
    selection_reason: str,
    window_rows: List[Dict[str, Any]],
    matched_rows: List[Dict[str, Any]],
    win32_only_matches: List[Dict[str, Any]],
    explicit_window_id: Optional[str],
) -> Dict[str, Any]:
    parsed_repo_counts: Dict[str, int] = {}
    for row in window_rows:
        parsed_key = str(row.get("normalized_parsed_repo") or "").strip() or "(unparsed)"
        parsed_repo_counts[parsed_key] = parsed_repo_counts.get(parsed_key, 0) + 1

    explicit_id = str(explicit_window_id or "").strip() or None
    explicit_present_in_snapshot = bool(
        explicit_id and any(str(row.get("window_id") or "") == explicit_id for row in window_rows)
    )
    explicit_present_in_win32_only = bool(
        explicit_id and any(str(row.get("window_id") or "") == explicit_id for row in win32_only_matches)
    )
    explicit_matches_repo = bool(
        explicit_id and any(str(row.get("window_id") or "") == explicit_id for row in matched_rows)
    )

    reason_class = "selection_failed"
    if selection_reason == "operator_window_id_not_found":
        if explicit_present_in_snapshot and not explicit_matches_repo:
            reason_class = "explicit_window_id_points_to_other_visible_repo"
        elif explicit_present_in_win32_only and not explicit_matches_repo:
            reason_class = "explicit_window_id_points_to_off_desktop_repo_window"
        else:
            reason_class = "explicit_window_id_stale_or_not_present"
    elif selection_reason == "repo_window_detected_win32_only":
        reason_class = "repo_window_visible_to_win32_but_not_dispatch_eligible"
    elif selection_reason == "no_matching_repo_window":
        reason_class = "no_visible_repo_window_matches_aliases"
    elif selection_reason == "ambiguous_repo_window":
        reason_class = "multiple_visible_repo_windows_need_operator_choice"

    visible_alias_mismatch_samples: List[Dict[str, Any]] = []
    for row in window_rows:
        reasons = list(row.get("reasons") or [])
        if "alias_mismatch" not in reasons:
            continue
        visible_alias_mismatch_samples.append(
            {
                "window_id": row.get("window_id"),
                "title": row.get("title"),
                "parsed_repo": row.get("normalized_parsed_repo") or row.get("parsed_repo") or "",
                "is_foreground": bool(row.get("is_foreground")),
            }
        )
        if len(visible_alias_mismatch_samples) >= 3:
            break

    win32_only_samples = [
        {
            "window_id": row.get("window_id"),
            "title": row.get("title"),
            "parsed_repo": row.get("normalized_parsed_repo") or row.get("parsed_repo") or "",
            "is_visible": row.get("is_visible"),
            "is_cloaked": row.get("is_cloaked"),
        }
        for row in win32_only_matches[:3]
    ]

    return {
        "schema": "targeting_failure_summary_v1",
        "repo_id": repo_id,
        "selection_reason": selection_reason,
        "reason_class": reason_class,
        "aliases": sorted(aliases),
        "visible_windows_total": len(window_rows),
        "visible_repo_matches": len(matched_rows),
        "win32_only_repo_matches": len(win32_only_matches),
        "visible_parsed_repo_counts": parsed_repo_counts,
        "explicit_window_id": explicit_id,
        "explicit_window_id_present_in_visible_snapshot": explicit_present_in_snapshot,
        "explicit_window_id_present_in_win32_only_matches": explicit_present_in_win32_only,
        "explicit_window_id_matches_repo": explicit_matches_repo,
        "visible_alias_mismatch_samples": visible_alias_mismatch_samples,
        "win32_only_match_samples": win32_only_samples,
    }


def _build_preflight_operator_guidance(
    *,
    repo_id: str,
    aliases: set[str],
    selection: Dict[str, Any],
    window_rows: List[Dict[str, Any]],
    matched_rows: List[Dict[str, Any]],
    win32_only_matches: List[Dict[str, Any]],
    explicit_window_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    reason_code = str(selection.get("reason_code") or "")
    failure_summary = _build_targeting_failure_summary(
        repo_id=repo_id,
        aliases=aliases,
        selection_reason=reason_code,
        window_rows=window_rows,
        matched_rows=matched_rows,
        win32_only_matches=win32_only_matches,
        explicit_window_id=explicit_window_id,
    )
    if reason_code == "ambiguous_repo_window" and matched_rows:
        best_signature = _selection_rank_signature(matched_rows[0])
        tied_rows = [row for row in matched_rows if _selection_rank_signature(row) == best_signature]
        exact_commands = []
        for row in tied_rows:
            window_id = str(row.get("window_id") or "").strip()
            if not window_id:
                continue
            exact_commands.append(
                {
                    "window_id": window_id,
                    "window_index": row.get("window_index"),
                    "selection_rank": row.get("selection_rank"),
                    "title": row.get("title"),
                    "validation_path": _build_supported_validation_path(repo_id=repo_id, window_id=window_id),
                    "readiness_command": _build_preflight_command(
                        "--pilot-readiness-only",
                        "--pilot-readiness-repo",
                        repo_id,
                        "--pilot-window-id",
                        window_id,
                        "--json",
                    ),
                    "dry_run_command": _build_preflight_command(
                        "--pilot-live-dispatch",
                        "--pilot-dry-run",
                        "--pilot-dry-run-repo",
                        repo_id,
                        "--pilot-window-id",
                        window_id,
                        "--json",
                    ),
                    "scheduler_dry_run_command": _build_preflight_command(
                        "--pilot-live-dispatch",
                        "--pilot-dry-run",
                        "--pilot-window-id",
                        window_id,
                        "--json",
                    ),
                    "dry_run_scope_note": (
                        "Repo-targeted dry-run validates targeting before scheduler selection. "
                        "The scheduler-backed live dry-run command remains available separately when needed."
                    ),
                }
            )
        selection["ambiguous_window_ids"] = [row["window_id"] for row in exact_commands if row.get("window_id")]
        return {
            "schema": "operator_guidance_v1",
            "issue": "ambiguous_repo_window",
            "summary": "Multiple eligible repo windows share the same best match rank; preflight cannot auto-select one safely.",
            "recommended_actions": [
                "Choose one exact window_id from exact_target_commands and run readiness-only for that repo/window.",
                "Use repo-targeted dry-run only as a targeting rehearsal; scheduler-backed live dry-run remains a separate path.",
            ],
            "deterministic_validation_path": _build_supported_validation_path(repo_id=repo_id),
            "targeting_failure_summary": failure_summary,
            "exact_target_commands": exact_commands,
            "next_step": "run_readiness_only_with_exact_window_id",
        }
    if reason_code == "repo_window_detected_win32_only" and win32_only_matches:
        top_match = win32_only_matches[0]
        return {
            "schema": "operator_guidance_v1",
            "issue": "repo_window_detected_win32_only",
            "summary": "A matching repo window exists, but it is cloaked or off the active desktop and is not yet eligible for dispatch.",
            "recommended_actions": [
                "Bring the exact repo window onto the active desktop, then rerun preflight.",
                "After that window becomes visible, run readiness-only with the same repo/window id before any live dispatch.",
            ],
            "deterministic_validation_path": _build_supported_validation_path(
                repo_id=repo_id,
                window_id=str(top_match.get("window_id") or "").strip() or None,
            ),
            "targeting_failure_summary": failure_summary,
            "exact_target_commands": [
                {
                    "window_id": top_match.get("window_id"),
                    "title": top_match.get("title"),
                    "preflight_command": _build_preflight_command(
                        "--pilot-preflight",
                        "--pilot-preflight-repo",
                        repo_id,
                        "--json",
                    ),
                }
            ],
            "next_step": "bring_window_onto_active_desktop_and_rerun_preflight",
        }
    if reason_code == "no_matching_repo_window":
        return {
            "schema": "operator_guidance_v1",
            "issue": "no_matching_repo_window",
            "summary": "No eligible VS Code window matched the requested repo aliases in the live snapshot.",
            "recommended_actions": [
                "Open or restore the intended repo window, then rerun preflight.",
                "If the repo is already open, verify it is on the active desktop; if preflight finds it, use readiness-only as the deterministic validation step.",
            ],
            "deterministic_validation_path": _build_supported_validation_path(repo_id=repo_id),
            "targeting_failure_summary": failure_summary,
            "exact_target_commands": [
                {
                    "preflight_command": _build_preflight_command(
                        "--pilot-preflight",
                        "--pilot-preflight-repo",
                        repo_id,
                        "--json",
                    )
                }
            ],
            "next_step": "open_or_restore_repo_window_and_rerun_preflight",
        }
    if reason_code == "operator_window_id_not_found":
        requested_window_id = str(explicit_window_id or "").strip()
        return {
            "schema": "operator_guidance_v1",
            "issue": "operator_window_id_not_found",
            "summary": "The supplied window id is not a current match for the requested repo.",
            "recommended_actions": [
                "Rerun repo preflight and choose a window_id from the matched repo windows for that repo only.",
                "Use readiness-only with the fresh repo/window id; do not use live dry-run as a direct repo-targeting validator.",
            ],
            "deterministic_validation_path": _build_supported_validation_path(repo_id=repo_id),
            "targeting_failure_summary": failure_summary,
            "exact_target_commands": [
                {
                    "requested_window_id": requested_window_id,
                    "preflight_command": _build_preflight_command(
                        "--pilot-preflight",
                        "--pilot-preflight-repo",
                        repo_id,
                        "--json",
                    ),
                }
            ],
            "next_step": "rerun_preflight_choose_fresh_window_id_then_readiness_only",
        }
    return None


def _window_hwnd_from_id(window_id: str) -> Optional[int]:
    raw = str(window_id or "").strip()
    if not raw.startswith("hwnd:"):
        return None
    try:
        value = int(raw.split(":", 1)[1])
        return value if value > 0 else None
    except Exception:
        return None


def _enrich_snapshot_with_win32_diagnostics(
    snapshot: List[Dict[str, Any]],
    win32_diag: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows = [dict(row) for row in snapshot]
    win32_rows = win32_diag.get("windows", []) if isinstance(win32_diag, dict) else []
    by_hwnd: Dict[int, Dict[str, Any]] = {}
    for item in win32_rows:
        if not isinstance(item, dict):
            continue
        hwnd = item.get("hwnd")
        if isinstance(hwnd, int) and hwnd > 0:
            by_hwnd[hwnd] = item

    ui_hwnds: set[int] = set()
    for row in rows:
        hwnd = _window_hwnd_from_id(str(row.get("window_id", "")))
        if hwnd is None:
            row["win32_lookup"] = "no_hwnd"
            row["inclusion_reason"] = "included_by_uia_no_hwnd"
            continue
        ui_hwnds.add(hwnd)
        win32 = by_hwnd.get(hwnd)
        if not isinstance(win32, dict):
            row["win32_lookup"] = "not_found"
            row["inclusion_reason"] = "included_by_uia_missing_win32_match"
            continue
        row["win32_lookup"] = "matched"
        row["is_visible"] = bool(win32.get("is_visible"))
        row["is_minimized"] = bool(win32.get("is_minimized"))
        row["is_cloaked"] = bool(win32.get("is_cloaked"))
        row["cloaked_raw"] = win32.get("cloaked_raw")
        row["class_name"] = win32.get("class_name")
        row["inclusion_reason"] = "included_by_uia"

    omitted: List[Dict[str, Any]] = []
    for item in win32_rows:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("is_vscode_title_match")):
            continue
        hwnd = item.get("hwnd")
        if not isinstance(hwnd, int) or hwnd <= 0:
            continue
        if hwnd in ui_hwnds:
            continue
        omitted.append(
            {
                "window_id": item.get("window_id"),
                "title": item.get("title"),
                "class_name": item.get("class_name"),
                "is_visible": bool(item.get("is_visible")),
                "is_minimized": bool(item.get("is_minimized")),
                "is_cloaked": bool(item.get("is_cloaked")),
                "cloaked_raw": item.get("cloaked_raw"),
                "inclusion_reason": "omitted_from_uia_snapshot",
                "win32_reason": item.get("inclusion_reason"),
            }
        )
    omitted.sort(key=lambda row: str(row.get("window_id", "")))

    enum_diag = {
        "schema": "window_enumeration_diagnostics_v1",
        "uia_backend": "uia_root_children",
        "win32_backend": "EnumWindows",
        "win32_summary": win32_diag.get("summary", {}) if isinstance(win32_diag, dict) else {},
        "win32_error": win32_diag.get("error") if isinstance(win32_diag, dict) else None,
        "windows_omitted_from_uia": omitted,
        "summary": {
            "uia_vscode_windows": len(rows),
            "win32_vscode_windows": int((win32_diag.get("summary", {}) or {}).get("vscode_title_matches", 0)) if isinstance(win32_diag, dict) else 0,
            "windows_omitted_from_uia": len(omitted),
        },
    }
    return rows, enum_diag


def collect_enriched_window_snapshot(timeout: float = 0.5) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    snapshot = collect_window_snapshot(timeout=timeout)
    win32_diag = enumerate_vscode_windows_win32()
    return _enrich_snapshot_with_win32_diagnostics(snapshot, win32_diag)


def collect_window_snapshot(timeout: float = 0.5) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, win in enumerate(find_all_vscode_windows(timeout=timeout), start=1):
        try:
            title = (win.Name or "").strip()
        except Exception:
            continue
        parsed_repo = extract_repo_name_from_vscode_window_title(title) or ""
        rows.append(
            {
                "window_id": _window_id(win, idx),
                "title": title,
                "parsed_repo": parsed_repo,
                "normalized_parsed_repo": _normalize_repo_name(parsed_repo),
                "dispatch_reference": win,
            }
        )
    rows.sort(key=lambda row: (str(row.get("normalized_parsed_repo", "")), str(row.get("title", "")), str(row.get("window_id", ""))))
    for index, row in enumerate(rows, start=1):
        row["window_index"] = index
    return rows


def inspect_repo_window_targeting(
    *,
    repo_id: str,
    repo_root: Optional[str],
    window_index: Optional[int] = None,
    window_id: Optional[str] = None,
    windows: Optional[List[Dict[str, Any]]] = None,
    omitted_windows: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 0.5,
) -> Dict[str, Any]:
    aliases = _repo_aliases(repo_id, repo_root)
    window_rows = [dict(row) for row in (windows if windows is not None else collect_window_snapshot(timeout=timeout))]
    current_foreground_hwnd = int(get_root_window(int(get_foreground_window() or 0)))
    current_foreground_id = f"hwnd:{current_foreground_hwnd}" if current_foreground_hwnd > 0 else None

    matched_rows: List[Dict[str, Any]] = []
    win32_only_matches: List[Dict[str, Any]] = []
    title_counts: Dict[str, int] = {}
    for row in window_rows:
        title = str(row.get("title", ""))
        title_counts[title] = title_counts.get(title, 0) + 1

    evaluated_window_rows: List[Dict[str, Any]] = []
    for row in window_rows:
        evaluated = _evaluate_window_candidate(
            row,
            repo_id=repo_id,
            repo_root=repo_root,
            aliases=aliases,
            current_foreground_id=current_foreground_id,
            dispatch_eligible_on_match=True,
        )
        if title_counts.get(str(evaluated.get("title", "")), 0) > 1:
            reasons = list(evaluated.get("reasons") or [])
            if "duplicate_window_title" not in reasons:
                reasons.append("duplicate_window_title")
            evaluated["reasons"] = reasons
        evaluated["title_duplicate_count"] = int(title_counts.get(str(evaluated.get("title", "")), 0))
        evaluated_window_rows.append(evaluated)
        if bool(evaluated.get("dispatch_eligible")):
            matched_rows.append(evaluated)

    matched_rows.sort(key=_selection_sort_key)
    for rank, row in enumerate(matched_rows, start=1):
        row["selection_rank"] = rank

    for item in omitted_windows or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        parsed_repo = extract_repo_name_from_vscode_window_title(title) or ""
        evaluated = _evaluate_window_candidate(
            {
                "window_id": item.get("window_id"),
                "window_index": None,
                "title": title,
                "parsed_repo": parsed_repo,
                "normalized_parsed_repo": _normalize_repo_name(parsed_repo),
                "dispatch_reference": None,
                "diagnostic_source": "win32_omitted",
                "is_visible": item.get("is_visible"),
                "is_minimized": item.get("is_minimized"),
                "is_cloaked": item.get("is_cloaked"),
                "cloaked_raw": item.get("cloaked_raw"),
                "inclusion_reason": item.get("inclusion_reason"),
                "win32_lookup": "omitted_from_uia_snapshot",
            },
            repo_id=repo_id,
            repo_root=repo_root,
            aliases=aliases,
            current_foreground_id=current_foreground_id,
            dispatch_eligible_on_match=False,
        )
        evaluated["title_duplicate_count"] = 0
        if bool(evaluated.get("match_candidate")):
            win32_only_matches.append(evaluated)

    win32_only_matches.sort(key=_selection_sort_key)

    selection: Dict[str, Any] = {
        "status": "none",
        "reason_code": "no_matching_repo_window",
        "selected_window_id": None,
        "selected_window_title": None,
        "selected_window_index": None,
    }

    normalized_window_id = str(window_id or "").strip()
    if window_index is not None and window_index < 1:
        selection.update(
            {
                "status": "invalid_operator_selection",
                "reason_code": "operator_index_out_of_range",
            }
        )
    elif normalized_window_id and window_index is not None:
        selected_by_id = next((row for row in matched_rows if str(row.get("window_id")) == normalized_window_id), None)
        selected_by_index = matched_rows[window_index - 1] if 1 <= window_index <= len(matched_rows) else None
        if selected_by_id is None:
            selection.update({"status": "invalid_operator_selection", "reason_code": "operator_window_id_not_found"})
        elif selected_by_index is None:
            selection.update({"status": "invalid_operator_selection", "reason_code": "operator_index_out_of_range"})
        elif str(selected_by_id.get("window_id")) != str(selected_by_index.get("window_id")):
            selection.update({"status": "invalid_operator_selection", "reason_code": "operator_selector_conflict"})
        else:
            selection.update(
                {
                    "status": "selected",
                    "reason_code": "selected_by_operator_window_id",
                    "selected_window_id": selected_by_id.get("window_id"),
                    "selected_window_title": selected_by_id.get("title"),
                    "selected_window_index": selected_by_id.get("window_index"),
                }
            )
    elif normalized_window_id:
        selected_by_id = next((row for row in matched_rows if str(row.get("window_id")) == normalized_window_id), None)
        if selected_by_id is None:
            selection.update({"status": "invalid_operator_selection", "reason_code": "operator_window_id_not_found"})
        else:
            selection.update(
                {
                    "status": "selected",
                    "reason_code": "selected_by_operator_window_id",
                    "selected_window_id": selected_by_id.get("window_id"),
                    "selected_window_title": selected_by_id.get("title"),
                    "selected_window_index": selected_by_id.get("window_index"),
                }
            )
    elif window_index is not None:
        if 1 <= window_index <= len(matched_rows):
            selected = matched_rows[window_index - 1]
            selection.update(
                {
                    "status": "selected",
                    "reason_code": "selected_by_operator_index",
                    "selected_window_id": selected.get("window_id"),
                    "selected_window_title": selected.get("title"),
                    "selected_window_index": selected.get("window_index"),
                }
            )
        else:
            selection.update({"status": "invalid_operator_selection", "reason_code": "operator_index_out_of_range"})
    elif len(matched_rows) == 1:
        selected = matched_rows[0]
        selection.update(
            {
                "status": "selected",
                "reason_code": "selected_single_match",
                "selected_window_id": selected.get("window_id"),
                "selected_window_title": selected.get("title"),
                "selected_window_index": selected.get("window_index"),
            }
        )
    elif len(matched_rows) > 1:
        best_signature = _selection_rank_signature(matched_rows[0])
        best_rows = [row for row in matched_rows if _selection_rank_signature(row) == best_signature]
        if len(best_rows) == 1:
            selected = best_rows[0]
            selection.update(
                {
                    "status": "selected",
                    "reason_code": "selected_best_ranked_match",
                    "selected_window_id": selected.get("window_id"),
                    "selected_window_title": selected.get("title"),
                    "selected_window_index": selected.get("window_index"),
                }
            )
        else:
            selection.update({"status": "ambiguous", "reason_code": "ambiguous_repo_window"})
    elif win32_only_matches:
        top_match = win32_only_matches[0]
        selection.update(
            {
                "status": "deferred_visibility",
                "reason_code": "repo_window_detected_win32_only",
                "selected_window_id": top_match.get("window_id"),
                "selected_window_title": top_match.get("title"),
                "selected_window_index": None,
            }
        )

    operator_guidance = _build_preflight_operator_guidance(
        repo_id=repo_id,
        aliases=aliases,
        selection=selection,
        window_rows=evaluated_window_rows,
        matched_rows=matched_rows,
        win32_only_matches=win32_only_matches,
        explicit_window_id=normalized_window_id or None,
    )

    targeting_failure_summary = None
    if reason_code := str(selection.get("reason_code") or ""):
        if reason_code != "selected_single_match" and reason_code != "selected_best_ranked_match" and reason_code != "selected_by_operator_index" and reason_code != "selected_by_operator_window_id":
            targeting_failure_summary = _build_targeting_failure_summary(
                repo_id=repo_id,
                aliases=aliases,
                selection_reason=reason_code,
                window_rows=evaluated_window_rows,
                matched_rows=matched_rows,
                win32_only_matches=win32_only_matches,
                explicit_window_id=normalized_window_id or None,
            )

    return {
        "diagnostic_version": "window_match_v1",
        "ts": datetime.now(timezone.utc).isoformat(),
        "repo_id": repo_id,
        "repo_root": repo_root,
        "aliases": sorted(aliases),
        "windows": [
            {
                "window_id": row.get("window_id"),
                "window_index": row.get("window_index"),
                "title": row.get("title"),
                "parsed_repo": row.get("parsed_repo"),
                "normalized_parsed_repo": row.get("normalized_parsed_repo"),
                "match_method": row.get("match_method"),
                "confidence": row.get("confidence"),
                "alias_match": row.get("alias_match"),
                "reasons": row.get("reasons"),
                "dispatch_eligible": row.get("dispatch_eligible"),
                "is_foreground": row.get("is_foreground"),
                "is_auxiliary_window": row.get("is_auxiliary_window"),
                "title_duplicate_count": row.get("title_duplicate_count"),
                "is_visible": row.get("is_visible"),
                "is_minimized": row.get("is_minimized"),
                "is_cloaked": row.get("is_cloaked"),
                "cloaked_raw": row.get("cloaked_raw"),
                "inclusion_reason": row.get("inclusion_reason"),
                "win32_lookup": row.get("win32_lookup"),
            }
            for row in evaluated_window_rows
        ],
        "matched_windows": [
            {
                "window_id": row.get("window_id"),
                "window_index": row.get("window_index"),
                "title": row.get("title"),
                "parsed_repo": row.get("parsed_repo"),
                "match_method": row.get("match_method"),
                "confidence": row.get("confidence"),
                "reasons": row.get("reasons"),
                "is_foreground": row.get("is_foreground"),
                "is_auxiliary_window": row.get("is_auxiliary_window"),
                "title_duplicate_count": row.get("title_duplicate_count"),
                "selection_rank": row.get("selection_rank"),
                "is_visible": row.get("is_visible"),
                "is_minimized": row.get("is_minimized"),
                "is_cloaked": row.get("is_cloaked"),
                "inclusion_reason": row.get("inclusion_reason"),
            }
            for row in matched_rows
        ],
        "win32_only_matches": [
            {
                "window_id": row.get("window_id"),
                "title": row.get("title"),
                "parsed_repo": row.get("parsed_repo"),
                "match_method": row.get("match_method"),
                "confidence": row.get("confidence"),
                "reasons": row.get("reasons"),
                "is_auxiliary_window": row.get("is_auxiliary_window"),
                "is_visible": row.get("is_visible"),
                "is_minimized": row.get("is_minimized"),
                "is_cloaked": row.get("is_cloaked"),
                "inclusion_reason": row.get("inclusion_reason"),
            }
            for row in win32_only_matches
        ],
        "selection": selection,
        "operator_guidance": operator_guidance,
        "targeting_failure_summary": targeting_failure_summary,
        "summary": {
            "discovered_windows": len(evaluated_window_rows),
            "matched_windows": len(matched_rows),
            "win32_only_matches": len(win32_only_matches),
            "eligible_for_dispatch": bool(selection.get("status") == "selected" and matched_rows),
            "foreground_window_id": current_foreground_id,
        },
    }


def build_window_preflight(
    *,
    repo_targets: List[Tuple[str, Optional[str]]],
    window_index_by_repo: Optional[Dict[str, int]] = None,
    window_id_by_repo: Optional[Dict[str, str]] = None,
    timeout: float = 0.5,
) -> Dict[str, Any]:
    snapshot, enum_diag = collect_enriched_window_snapshot(timeout=timeout)
    omitted_windows = enum_diag.get("windows_omitted_from_uia", []) if isinstance(enum_diag, dict) else []
    evaluations: List[Dict[str, Any]] = []
    for repo_id, repo_root in repo_targets:
        idx = None
        if isinstance(window_index_by_repo, dict):
            idx = window_index_by_repo.get(str(repo_id).strip().lower())
        explicit_window_id = None
        if isinstance(window_id_by_repo, dict):
            explicit_window_id = window_id_by_repo.get(str(repo_id).strip().lower())
        evaluations.append(
            inspect_repo_window_targeting(
                repo_id=repo_id,
                repo_root=repo_root,
                window_index=idx,
                window_id=explicit_window_id,
                windows=snapshot,
                omitted_windows=omitted_windows,
            )
        )

    by_repo = {
        str(row.get("repo_id", "")).strip().lower(): [
            item.get("window_id") for item in row.get("matched_windows", []) if isinstance(item, dict)
        ]
        for row in evaluations
    }
    return {
        "diagnostic_version": "window_preflight_v1",
        "mode": "pilot_preflight",
        "ts": datetime.now(timezone.utc).isoformat(),
        "windows_discovered": [
            {
                "window_id": row.get("window_id"),
                "window_index": row.get("window_index"),
                "title": row.get("title"),
                "parsed_repo": row.get("parsed_repo"),
                "is_visible": row.get("is_visible"),
                "is_minimized": row.get("is_minimized"),
                "is_cloaked": row.get("is_cloaked"),
                "cloaked_raw": row.get("cloaked_raw"),
                "inclusion_reason": row.get("inclusion_reason"),
                "win32_lookup": row.get("win32_lookup"),
            }
            for row in snapshot
        ],
        "window_enumeration_diagnostics": enum_diag,
        "repo_diagnostics": evaluations,
        "eligible_targets_by_repo": by_repo,
        "summary": {
            "windows_total": len(snapshot),
            "repos_total": len(evaluations),
            "repos_eligible": sum(1 for row in evaluations if row.get("summary", {}).get("eligible_for_dispatch")),
            "windows_omitted_from_uia": int((enum_diag.get("summary", {}) or {}).get("windows_omitted_from_uia", 0)),
        },
    }


def _find_matching_windows(repo_id: str, repo_root: Optional[str]) -> List[Tuple[str, object]]:
    snapshot = collect_window_snapshot(timeout=0.5)
    analysis = inspect_repo_window_targeting(repo_id=repo_id, repo_root=repo_root, windows=snapshot)
    selected_ids = {str(row.get("window_id", "")) for row in analysis.get("matched_windows", []) if isinstance(row, dict)}
    matches: List[Tuple[str, object]] = []
    for row in snapshot:
        if str(row.get("window_id", "")) not in selected_ids:
            continue
        win = row.get("dispatch_reference")
        if win is None:
            continue
        matches.append((str(row.get("title", "")), win))
    return matches


def _window_handle_for_dispatch(target_win: object, selected_window_id: str) -> int:
    parsed = _window_hwnd_from_id(selected_window_id)
    if parsed:
        return int(parsed)
    handle = getattr(target_win, "NativeWindowHandle", None)
    if isinstance(handle, int) and handle > 0:
        return int(handle)
    return 0


def _foreground_snapshot() -> Dict[str, Any]:
    fg_hwnd = int(get_root_window(int(get_foreground_window() or 0)))
    fg_window_id = f"hwnd:{fg_hwnd}" if fg_hwnd > 0 else None
    fg_title = None
    try:
        for row in collect_window_snapshot(timeout=0.2):
            if str(row.get("window_id")) == str(fg_window_id):
                fg_title = str(row.get("title") or "")
                break
    except Exception:
        fg_title = None
    return {
        "foreground_hwnd": fg_hwnd if fg_hwnd > 0 else None,
        "foreground_window_id": fg_window_id,
        "foreground_window_title": fg_title,
    }


def _is_target_foreground(hwnd: int) -> bool:
    if hwnd <= 0:
        return False
    try:
        return int(get_root_window(int(get_foreground_window() or 0))) == int(hwnd)
    except Exception:
        return False


def _probe_dispatch_readiness(
    *,
    target_win: object,
    selected_window_id: str,
    selected_window_title: str,
    safe_activate: bool,
) -> Dict[str, Any]:
    hwnd = _window_handle_for_dispatch(target_win, selected_window_id)
    foreground_before = _is_target_foreground(hwnd)
    fg_before_snapshot = _foreground_snapshot()
    activation_attempted = False
    activation_succeeded = False

    if safe_activate and not foreground_before:
        activation_attempted = True
        activation_succeeded = bool(ensure_window_focus(target_win, description=selected_window_title or "repo_window"))

    foreground_after = _is_target_foreground(hwnd)
    fg_after_snapshot = _foreground_snapshot()

    editor = None
    input_box = None
    send_button = None
    probe_error = None
    if foreground_after:
        try:
            editor = find_chat_editor_control(target_win)
            input_box = find_chat_input_box(target_win)
            send_button = find_send_button(target_win)
        except Exception as exc:
            probe_error = str(exc)

    panel_detected = bool(editor is not None or input_box is not None)
    input_detected = bool(editor is not None or input_box is not None)
    sendable = bool(foreground_after and panel_detected and input_detected)
    reason_code = "ready_to_send"
    if not foreground_after:
        reason_code = "target_not_foreground"
    elif not panel_detected:
        reason_code = "chat_panel_not_detected"
    elif not input_detected:
        reason_code = "chat_input_not_detected"
    elif probe_error:
        reason_code = "readiness_probe_error"

    summary = "ready"
    if reason_code != "ready_to_send":
        summary = f"blocked:{reason_code}"

    selected_window_summary = {
        "window_id": selected_window_id,
        "window_title": selected_window_title,
        "target_hwnd": hwnd if hwnd > 0 else None,
        "is_target_foreground": bool(foreground_after),
    }

    operator_guidance = None
    if reason_code == "target_not_foreground":
        operator_guidance = {
            "schema": "operator_guidance_v1",
            "issue": "target_not_foreground",
            "selected_window": selected_window_summary,
            "foreground_window": fg_after_snapshot,
            "recommended_actions": [
                "Bring the selected window to the front (exact id/title shown above).",
                "Click inside the chat input box in that same window.",
                "Run readiness-only probe for this window id.",
                "Run live dispatch again only after readiness reports ready_to_send.",
            ],
        }

    return {
        "schema": "dispatch_readiness_v1",
        "mode": "safe_activate" if safe_activate else "operator_assisted",
        "target_window_id": selected_window_id,
        "target_window_title": selected_window_title,
        "target_hwnd": hwnd if hwnd > 0 else None,
        "foreground": {
            "before": foreground_before,
            "after": foreground_after,
            "activation_attempted": activation_attempted,
            "activation_succeeded": activation_succeeded,
            "snapshot_before": fg_before_snapshot,
            "snapshot_after": fg_after_snapshot,
        },
        "selected_window_summary": selected_window_summary,
        "panel_detected": panel_detected,
        "input_detected": input_detected,
        "send_button_detected": bool(send_button is not None),
        "active_sendable": sendable,
        "reason_code": reason_code,
        "summary": summary,
        "legacy_send_policy": {
            "enable_send_to_inactive_panels": bool(ENABLE_SEND_TO_INACTIVE_PANELS),
            "would_block_without_safe_mode": bool(not ENABLE_SEND_TO_INACTIVE_PANELS),
        },
        "operator_guidance": operator_guidance,
        "probe_error": probe_error,
    }


def _send_text_to_active_chat(target_win: object, prompt_text: str, readiness: Dict[str, Any]) -> Tuple[bool, str]:
    import uiautomation as auto

    if not bool(readiness.get("active_sendable")):
        return False, str(readiness.get("reason_code") or "dispatch_not_ready")

    hwnd = int(readiness.get("target_hwnd") or 0)
    if not _is_target_foreground(hwnd):
        return False, "target_not_foreground"

    editor = find_chat_editor_control(target_win)
    input_box = editor or find_chat_input_box(target_win)
    if input_box is None:
        return False, "chat_input_not_detected"

    try:
        input_box.SetFocus()
    except Exception:
        try:
            input_box.Click(simulateMove=False)
        except Exception:
            return False, "chat_input_not_focusable"

    time.sleep(0.05)
    auto.SendKeys(prompt_text)
    time.sleep(0.05)

    send_btn = find_send_button(target_win)
    if send_btn is None:
        auto.SendKeys("{Enter}")
    else:
        try:
            send_btn.Click(simulateMove=False)
        except Exception:
            auto.SendKeys("{Enter}")
    time.sleep(0.05)
    return True, "sent"


def dispatch_prompt_to_repo_window(
    *,
    repo_id: str,
    repo_root: Optional[str],
    prompt_text: str,
    dry_run: bool = False,
    window_index: Optional[int] = None,
    window_id: Optional[str] = None,
    safe_activate: bool = False,
    readiness_only: bool = False,
) -> PilotDispatchResult:
    snapshot, enum_diag = collect_enriched_window_snapshot(timeout=0.5)
    diagnostics = inspect_repo_window_targeting(
        repo_id=repo_id,
        repo_root=repo_root,
        window_index=window_index,
        window_id=window_id,
        windows=snapshot,
        omitted_windows=enum_diag.get("windows_omitted_from_uia", []) if isinstance(enum_diag, dict) else None,
    )
    diagnostics["window_enumeration_diagnostics"] = enum_diag
    matched_rows = diagnostics.get("matched_windows", [])
    titles = [str(row.get("title", "")) for row in matched_rows if isinstance(row, dict)]
    selected_id = str((diagnostics.get("selection") or {}).get("selected_window_id") or "")
    selected_title = str((diagnostics.get("selection") or {}).get("selected_window_title") or "") or None
    reason = str((diagnostics.get("selection") or {}).get("reason_code") or "no_matching_repo_window")

    if not matched_rows:
        return PilotDispatchResult(
            success=False,
            reason=reason,
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=None,
            selected_window_id=None,
            diagnostics=diagnostics,
        )
    if str((diagnostics.get("selection") or {}).get("status") or "") != "selected":
        return PilotDispatchResult(
            success=False,
            reason=reason,
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=selected_title,
            selected_window_id=selected_id or None,
            diagnostics=diagnostics,
        )

    if dry_run:
        return PilotDispatchResult(
            success=True,
            reason="dry_run",
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=selected_title,
            selected_window_id=selected_id or None,
            diagnostics=diagnostics,
        )

    target_win = None
    for row in snapshot:
        if str(row.get("window_id", "")) == selected_id:
            target_win = row.get("dispatch_reference")
            break

    if target_win is None:
        diagnostics.setdefault("selection", {})["status"] = "none"
        diagnostics.setdefault("selection", {})["reason_code"] = "selected_window_missing"
        return PilotDispatchResult(
            success=False,
            reason="selected_window_missing",
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=selected_title,
            selected_window_id=selected_id or None,
            diagnostics=diagnostics,
        )

    if not ensure_window_focus(target_win, description=selected_title or "repo_window"):
        diagnostics.setdefault("selection", {})["status"] = "focus_failed"
        diagnostics.setdefault("selection", {})["reason_code"] = "window_focus_failed"
        diagnostics["dispatch_readiness"] = {
            "schema": "dispatch_readiness_v1",
            "mode": "safe_activate" if safe_activate else "operator_assisted",
            "target_window_id": selected_id,
            "target_window_title": selected_title,
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
            "reason_code": "window_focus_failed",
            "summary": "blocked:window_focus_failed",
            "legacy_send_policy": {
                "enable_send_to_inactive_panels": bool(ENABLE_SEND_TO_INACTIVE_PANELS),
                "would_block_without_safe_mode": bool(not ENABLE_SEND_TO_INACTIVE_PANELS),
            },
            "probe_error": None,
        }
        return PilotDispatchResult(
            success=False,
            reason="window_focus_failed",
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=selected_title,
            selected_window_id=selected_id or None,
            diagnostics=diagnostics,
        )

    readiness = _probe_dispatch_readiness(
        target_win=target_win,
        selected_window_id=selected_id,
        selected_window_title=selected_title or "",
        safe_activate=bool(safe_activate),
    )
    readiness["enforcement_mode"] = "hard_fail_closed" if safe_activate else "advisory_only"
    diagnostics["dispatch_readiness"] = readiness
    if isinstance(readiness.get("operator_guidance"), dict):
        diagnostics["operator_guidance"] = readiness.get("operator_guidance")

    if readiness_only:
        readiness_reason = str(readiness.get("reason_code") or "dispatch_not_ready")
        if bool(readiness.get("active_sendable")):
            diagnostics.setdefault("selection", {})["status"] = "readiness_ready"
            diagnostics.setdefault("selection", {})["reason_code"] = "ready_to_send"
            return PilotDispatchResult(
                success=True,
                reason="readiness_ready",
                repo_id=repo_id,
                matched_window_titles=titles,
                selected_window_title=selected_title,
                selected_window_id=selected_id or None,
                diagnostics=diagnostics,
            )

        diagnostics.setdefault("selection", {})["status"] = "dispatch_not_ready"
        diagnostics.setdefault("selection", {})["reason_code"] = readiness_reason
        return PilotDispatchResult(
            success=False,
            reason="dispatch_not_ready",
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=selected_title,
            selected_window_id=selected_id or None,
            diagnostics=diagnostics,
        )

    if safe_activate and not bool(readiness.get("active_sendable")):
        readiness_reason = str(readiness.get("reason_code") or "dispatch_not_ready")
        diagnostics.setdefault("selection", {})["status"] = "dispatch_not_ready"
        diagnostics.setdefault("selection", {})["reason_code"] = readiness_reason
        return PilotDispatchResult(
            success=False,
            reason="dispatch_not_ready",
            repo_id=repo_id,
            matched_window_titles=titles,
            selected_window_title=selected_title,
            selected_window_id=selected_id or None,
            diagnostics=diagnostics,
        )

    send_reason = "sent"
    if safe_activate:
        sent, send_reason = _send_text_to_active_chat(target_win, prompt_text, readiness)
    else:
        sent = send_text_to_chat(target_win, prompt_text)
        send_reason = "sent" if sent else "send_text_failed"
    if not sent:
        diagnostics.setdefault("selection", {})["status"] = "send_failed"
        diagnostics.setdefault("selection", {})["reason_code"] = send_reason
    return PilotDispatchResult(
        success=bool(sent),
        reason="sent" if sent else send_reason,
        repo_id=repo_id,
        matched_window_titles=titles,
        selected_window_title=selected_title,
        selected_window_id=selected_id or None,
        diagnostics=diagnostics,
    )


def _report_candidates(report_root: Path, run_id: str, repo_id: str) -> List[Path]:
    return [
        report_root / f"{run_id}.json",
        report_root / f"{run_id}.yaml",
        report_root / f"{run_id}.yml",
        report_root / f"{run_id}.md",
        report_root / f"{run_id}.txt",
        report_root / repo_id / f"{run_id}.json",
        report_root / repo_id / f"{run_id}.yaml",
        report_root / repo_id / f"{run_id}.yml",
        report_root / repo_id / f"{run_id}.md",
        report_root / repo_id / f"{run_id}.txt",
    ]


def _synthetic_malformed_report(raw_text: str) -> WorkerCompletionReport:
    return WorkerCompletionReport(
        status=WorkerOutcome.FAILED,
        summary="Malformed worker report",
        blockers=["malformed_report"],
        raw_text=raw_text,
    )


def poll_worker_outcome(
    *,
    run_id: str,
    repo_id: str,
    repo_root: Optional[str],
    report_root: Path,
    poll_seconds: int,
    poll_interval_seconds: int = 5,
    allow_panel_fallback: bool = True,
    strict_mode: bool = False,
    sandbox_mode: bool = False,
    sandbox_allowed_report_paths: Optional[List[str]] = None,
) -> PilotResponsePollResult:
    start = time.time()
    deadline = start + max(0, poll_seconds)
    malformed_seen = False
    last_malformed_raw = ""
    seen_hashes: set[str] = set()
    accepted_hash: Optional[str] = None
    candidate_checks = 0
    rejected: List[Dict[str, Any]] = []
    accepted_source: Optional[str] = None
    accepted_path: Optional[str] = None
    accepted_parse_mode: Optional[str] = None
    channels_polled_order: List[str] = []
    channel_attempts: Dict[str, int] = {"report_file": 0, "panel_markers": 0}
    candidate_events: List[Dict[str, Any]] = []
    rejection_counts: Dict[str, int] = {}
    close_but_invalid_hints: List[Dict[str, Any]] = []
    rounds_total = 0
    sandbox_allowed_paths_canonical: set[str] = set()
    if sandbox_mode and sandbox_allowed_report_paths:
        for raw_path in sandbox_allowed_report_paths:
            try:
                sandbox_allowed_paths_canonical.add(str(Path(raw_path).resolve(strict=False)))
            except Exception:
                continue

    def _record_channel_attempt(channel: str) -> None:
        if channel not in channels_polled_order:
            channels_polled_order.append(channel)
        channel_attempts[channel] = channel_attempts.get(channel, 0) + 1

    def _record_candidate_event(
        *,
        channel: str,
        path: Optional[str],
        candidate_sha256: str,
        raw_len: int,
        verdict: str,
        reason: Optional[str] = None,
    ) -> None:
        elapsed_ms = int((time.time() - start) * 1000)
        event: Dict[str, Any] = {
            "round_index": rounds_total,
            "elapsed_ms": elapsed_ms,
            "channel": channel,
            "path": path,
            "candidate_sha8": candidate_sha256[:8],
            "bytes": raw_len,
            "verdict": verdict,
        }
        if reason:
            event["reason"] = reason
        candidate_events.append(event)
        if len(candidate_events) > 25:
            del candidate_events[0]

    def _diag_payload(*, waiting_state: str) -> Dict[str, Any]:
        elapsed_ms = int((time.time() - start) * 1000)
        remaining_ms = max(0, int((deadline - time.time()) * 1000))
        primary_rejection = _primary_rejection()
        operator_guidance = _operator_guidance(waiting_state=waiting_state, primary_rejection=primary_rejection)
        return {
            "schema": "pilot_poll_diagnostics_v1",
            "strict_mode": strict_mode,
            "sandbox_mode": sandbox_mode,
            "sandbox_acceptance_constraints": {
                "allowed_statuses": ["partial", "blocked"] if sandbox_mode else None,
                "require_empty_files_changed": sandbox_mode,
                "require_validation_not_run": sandbox_mode,
                "require_validation_entries": sandbox_mode,
                "require_empty_handover_written_to": sandbox_mode,
                "allowed_report_paths": sorted(sandbox_allowed_paths_canonical) if sandbox_mode else None,
            },
            "poll_seconds": max(0, poll_seconds),
            "poll_interval_seconds": max(1, poll_interval_seconds),
            "rounds_total": rounds_total,
            "channels_checked": ["report_file"] + (["panel_markers"] if allow_panel_fallback else []),
            "channels_polled": channels_polled_order,
            "channel_attempts": channel_attempts,
            "candidate_count": candidate_checks,
            "candidates_found_total": candidate_checks,
            "candidate_events": candidate_events,
            "rejection_counts_by_reason": rejection_counts,
            "rejected_candidates": rejected,
            "close_but_invalid_hints": close_but_invalid_hints,
            "primary_rejection": primary_rejection,
            "operator_guidance": operator_guidance,
            "accepted_source": accepted_source,
            "accepted_report_path": accepted_path,
            "accepted_parse_mode": accepted_parse_mode,
            "waiting_status": {
                "state": waiting_state,
                "elapsed_ms": elapsed_ms,
                "remaining_ms": remaining_ms,
                "last_rejection_reason": rejected[-1]["reason"] if rejected else None,
                "primary_rejection_reason": primary_rejection.get("reason") if isinstance(primary_rejection, dict) else None,
                "primary_hint_code": primary_rejection.get("hint_code") if isinstance(primary_rejection, dict) else None,
                "primary_hint_text": primary_rejection.get("hint_text") if isinstance(primary_rejection, dict) else None,
                "operator_next_step": operator_guidance.get("next_step") if isinstance(operator_guidance, dict) else None,
                "channels_expected": ["report_file"] + (["panel_markers"] if allow_panel_fallback else []),
                "still_waiting_for": "strict valid marker-framed JSON response" if strict_mode else "structured worker report",
            },
        }

    def _primary_rejection() -> Optional[Dict[str, Any]]:
        if not rejected:
            return None
        row = dict(rejected[-1])
        reason = str(row.get("reason") or "").strip()
        guidance = _strict_rejection_guidance(reason, row.get("detail") if isinstance(row.get("detail"), dict) else None)
        if guidance is not None:
            row.update(guidance)
        return row

    def _operator_guidance(*, waiting_state: str, primary_rejection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if waiting_state == "accepted":
            return {
                "issue": "accepted",
                "summary": "Strict response accepted.",
                "recommended_actions": [],
                "next_step": "continue_or_finalize",
            }
        if waiting_state == "timeout":
            actions = [
                "Confirm the agent wrote a report file or sent a reply before the poll timeout expired.",
                "If strict mode is enabled, resend the minimal marker-framed JSON reply with no extra text.",
            ]
            if allow_panel_fallback:
                actions.append("If panel fallback is in use, rerun preflight or readiness and set --pilot-window-id when multiple repo windows exist.")
            return {
                "issue": "response_timeout",
                "summary": "No acceptable worker response was observed before timeout.",
                "recommended_actions": actions,
                "next_step": "confirm_response_source_and_retry",
            }
        if isinstance(primary_rejection, dict):
            action = str(primary_rejection.get("operator_action") or "Check the strict response contract and resend a clean marker-framed JSON reply.")
            recommended_actions = [action]
            if sandbox_mode:
                recommended_actions.append(
                    "Sandbox self-test only accepts report-file replies with status partial|blocked, empty files_changed, not_run validation rows, and empty handover_written_to."
                )
            return {
                "issue": str(primary_rejection.get("category") or "strict_response_rejected"),
                "summary": str(primary_rejection.get("hint_text") or "Strict response was rejected."),
                "reason": primary_rejection.get("reason"),
                "hint_code": primary_rejection.get("hint_code"),
                "recommended_actions": recommended_actions,
                "next_step": primary_rejection.get("operator_next_step") or "retry_strict_response",
            }
        return {
            "issue": "strict_response_rejected",
            "summary": "Strict response was rejected, but no specific guidance was recorded.",
            "recommended_actions": ["Inspect rejected_candidates and resend a clean marker-framed JSON response."],
            "next_step": "inspect_rejected_candidates",
        }

    def _reject(
        *,
        channel: str,
        reason: str,
        path: Optional[str],
        candidate_sha256: Optional[str] = None,
        raw_len: Optional[int] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        nonlocal malformed_seen
        malformed_seen = True
        row: Dict[str, Any] = {"channel": channel, "path": path, "reason": reason}
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        if candidate_sha256:
            row["candidate_sha256"] = candidate_sha256
        if raw_len is not None:
            row["raw_len"] = raw_len
        hint = _close_but_invalid_hint(reason)
        if hint is not None:
            row.update(hint)
            close_but_invalid_hints.append(
                {
                    "channel": channel,
                    "path": path,
                    "reason": reason,
                    **hint,
                }
            )
            if len(close_but_invalid_hints) > 20:
                del close_but_invalid_hints[0]
        if detail:
            row["detail"] = detail
        rejected.append(row)
        if candidate_sha256 is not None and raw_len is not None:
            _record_candidate_event(
                channel=channel,
                path=path,
                candidate_sha256=candidate_sha256,
                raw_len=raw_len,
                verdict="rejected",
                reason=reason,
            )

    def _candidate_hash(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _try_accept(raw: str, *, channel: str, path: Optional[str]) -> Optional[WorkerCompletionReport]:
        nonlocal candidate_checks, last_malformed_raw, accepted_hash, accepted_source, accepted_path, accepted_parse_mode
        candidate_checks += 1
        digest = _candidate_hash(raw)
        if digest in seen_hashes:
            _reject(
                channel=channel,
                reason="E_DUPLICATE_CANDIDATE",
                path=path,
                candidate_sha256=digest,
                raw_len=len(raw),
            )
            return None
        seen_hashes.add(digest)

        if strict_mode:
            report, reject_code, meta = parse_worker_completion_report_strict(
                raw_text=raw,
                expected_run_id=run_id,
                expected_repo_id=repo_id,
                source_channel=channel,
            )
            if report is None:
                last_malformed_raw = raw
                _reject(
                    channel=channel,
                    reason=reject_code or "E_STRICT_PARSE_FAILED",
                    path=path,
                    candidate_sha256=digest,
                    raw_len=len(raw),
                    detail=meta,
                )
                return None

            if sandbox_mode:
                canonical_path = None
                if path:
                    try:
                        canonical_path = str(Path(path).resolve(strict=False))
                    except Exception:
                        canonical_path = path
                if channel != "report_file":
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_CHANNEL_NOT_ALLOWED",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                    )
                    return None
                if canonical_path is None:
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_REPORT_PATH_MISSING",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                    )
                    return None
                if sandbox_allowed_paths_canonical and canonical_path not in sandbox_allowed_paths_canonical:
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_REPORT_PATH_NOT_ALLOWED",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                        detail={"allowed_report_paths": sorted(sandbox_allowed_paths_canonical)},
                    )
                    return None
                if report.status.value not in {"partial", "blocked"}:
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_STATUS_NOT_TRIAGE",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                        detail={"status": report.status.value},
                    )
                    return None
                if report.files_changed:
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_FILES_CHANGED",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                        detail={"files_changed_count": len(report.files_changed)},
                    )
                    return None
                if not report.tests_validation_run:
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_VALIDATION_REQUIRED",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                    )
                    return None
                if any((run.result or "").strip().lower() != "not_run" for run in report.tests_validation_run):
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_VALIDATION_EXECUTED",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                        detail={
                            "validation_results": [
                                (run.result or "").strip().lower() for run in report.tests_validation_run
                            ]
                        },
                    )
                    return None
                if report.handover_report_path:
                    _reject(
                        channel=channel,
                        reason="E_SANDBOX_HANDOVER_NOT_ALLOWED",
                        path=path,
                        candidate_sha256=digest,
                        raw_len=len(raw),
                        detail={"handover_written_to": report.handover_report_path},
                    )
                    return None

            if accepted_hash and accepted_hash != digest:
                _reject(
                    channel=channel,
                    reason="E_CONFLICTING_CANDIDATE",
                    path=path,
                    candidate_sha256=digest,
                    raw_len=len(raw),
                )
                return None
            accepted_hash = digest
            accepted_source = channel
            accepted_path = path
            accepted_parse_mode = str((meta or {}).get("parse_mode") or "strict_marked_json")
            return report

        report = parse_worker_completion_report(raw)
        if report is None:
            last_malformed_raw = raw
            _reject(
                channel=channel,
                reason="E_PARSE_FAILED",
                path=path,
                candidate_sha256=digest,
                raw_len=len(raw),
            )
            return None
        accepted_source = channel
        accepted_path = path
        accepted_parse_mode = "json_or_text"
        return report

    first_poll = True
    while first_poll or time.time() <= deadline:
        first_poll = False
        rounds_total += 1
        _record_channel_attempt("report_file")
        # Preferred source: structured worker report files.
        for path in _report_candidates(report_root, run_id, repo_id):
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8", errors="ignore")
            report = _try_accept(raw, channel="report_file", path=str(path))
            if report is not None:
                if accepted_hash:
                    _record_candidate_event(
                        channel=accepted_source or "report_file",
                        path=accepted_path,
                        candidate_sha256=accepted_hash,
                        raw_len=len(raw),
                        verdict="accepted",
                    )
                return PilotResponsePollResult(
                    report=report,
                    source=accepted_source or "report_file",
                    report_path=accepted_path,
                    parse_mode=accepted_parse_mode,
                    elapsed_ms=int((time.time() - start) * 1000),
                    malformed_seen=malformed_seen,
                    response_diagnostics=_diag_payload(waiting_state="accepted"),
                )

        # Fallback source: panel output text in matching repo window.
        if allow_panel_fallback:
            _record_channel_attempt("panel_markers")
            matches = _find_matching_windows(repo_id, repo_root)
            if len(matches) == 1:
                _, win = matches[0]
                try:
                    panel_output = get_panel_output_text(win)
                except Exception:
                    panel_output = ""
                report = _try_accept(panel_output, channel="panel_markers", path=None)
                if report is not None:
                    if accepted_hash:
                        _record_candidate_event(
                            channel=accepted_source or "panel_markers",
                            path=accepted_path,
                            candidate_sha256=accepted_hash,
                            raw_len=len(panel_output),
                            verdict="accepted",
                        )
                    return PilotResponsePollResult(
                        report=report,
                        source=accepted_source or "panel_markers",
                        report_path=accepted_path,
                        parse_mode=accepted_parse_mode,
                        elapsed_ms=int((time.time() - start) * 1000),
                        malformed_seen=malformed_seen,
                        response_diagnostics=_diag_payload(waiting_state="accepted"),
                    )
            elif strict_mode and len(matches) > 1:
                _reject(channel="panel_markers", reason="E_AMBIGUOUS_REPO_WINDOW", path=None)

        if poll_seconds <= 0:
            break
        time.sleep(max(1, poll_interval_seconds))

    if malformed_seen:
        return PilotResponsePollResult(
            report=_synthetic_malformed_report(last_malformed_raw),
            source="malformed_report",
            report_path=None,
            parse_mode="strict_failed_parse" if strict_mode else "failed_parse",
            elapsed_ms=int((time.time() - start) * 1000),
            malformed_seen=True,
            response_diagnostics=_diag_payload(waiting_state="malformed"),
        )

    return PilotResponsePollResult(
        report=None,
        source="timeout",
        report_path=None,
        parse_mode=None,
        elapsed_ms=int((time.time() - start) * 1000),
        malformed_seen=False,
        response_diagnostics=_diag_payload(waiting_state="timeout"),
    )
