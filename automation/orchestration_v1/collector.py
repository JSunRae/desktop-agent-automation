from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from automation import north_star
from automation.cross_repo_todo_ingestion import (
    TodoItem,
    get_cross_repo_todo_service,
    parse_todo_markdown,
)
from automation.north_star import ActiveTask
from automation.orchestration_v1.models import (
    ManagedRepoConfig,
    RepoContextBundle,
    Severity,
    StructuredTaskItem,
    WorkCategory,
    WorkItem,
    WorkStatus,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_CHECKBOX_RE = re.compile(r"^\s*\[\s?[xX ]\]\s+(.+?)\s*$")
_TASK_PREFIX_RE = re.compile(
    r"^\s*(?:TODO|ACTION|NEXT(?:\s+STEP)?S?|OPEN\s+ITEMS?|FOLLOW\s*UP|FIXME)\s*[:\-]\s+(.+?)\s*$",
    re.IGNORECASE,
)
_TICKET_TASK_RE = re.compile(r"^\s*[A-Z]{2,12}-\d+\s*[:\-]\s+(.+?)\s*$")
_ACTIONABLE_SENTENCE_RE = re.compile(
    r"^\s*(?:must|should|need\s+to|needs\s+to|follow\s*up|investigate|fix|implement|add|update|remove|refactor|write|verify|review|harden|test|document)\b.{4,}$",
    re.IGNORECASE,
)
_ACTIONABLE_HEADING_KEYWORDS = (
    "todo",
    "next",
    "action",
    "open",
    "follow-up",
    "follow up",
    "handover",
    "backlog",
)
_STRUCTURED_LIST_KEYS = (
    "tasks",
    "items",
    "todos",
    "blockers",
    "risks",
    "next_recommended_actions",
    "next_actions",
    "follow_ups",
)
_STRUCTURED_TEXT_KEYS = ("summary",)
_DEFAULT_CONSTRAINTS = [
    "respect_repo_local_instructions",
    "do_not_interrupt_protected_processes",
    "operate_within_managed_repo_boundary",
]

LOGGER = logging.getLogger(__name__)


def _read_text(path: Path, max_chars: int = 12000) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return raw[:max_chars] if len(raw) > max_chars else raw


def _relative_path(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _glob_existing(base: Path, patterns: Sequence[str], limit: int = 40) -> Tuple[List[Path], Dict[str, int]]:
    found: List[Path] = []
    seen: set[str] = set()
    matched_counts: Dict[str, int] = {str(pattern): 0 for pattern in patterns}
    for pattern in patterns:
        try:
            candidates = list(base.glob(pattern))
        except OSError:
            continue
        for candidate in candidates:
            if not candidate.is_file():
                continue
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
            matched_counts[str(pattern)] = matched_counts.get(str(pattern), 0) + 1
            if len(found) >= limit:
                return found, matched_counts
    return found, matched_counts


def _source_diagnostics(
    *,
    configured_entries: Sequence[str],
    matched_paths: Sequence[Path],
    matched_counts: Dict[str, int] | None = None,
    text_blocks: int = 0,
) -> Dict[str, object]:
    normalized_entries = [str(entry) for entry in configured_entries if str(entry).strip()]
    counts = matched_counts or {}
    unmatched_entries = [entry for entry in normalized_entries if counts.get(entry, 0) <= 0]
    return {
        "configured_entries": normalized_entries,
        "matched_files": [str(path).replace("\\", "/") for path in matched_paths],
        "matched_file_count": len(matched_paths),
        "matched_entry_count": sum(1 for entry in normalized_entries if counts.get(entry, 0) > 0),
        "unmatched_entries": unmatched_entries,
        "text_blocks": text_blocks,
    }


def _find_nearby_task_candidates(base: Path, limit: int = 8) -> List[str]:
    patterns = [
        "*Todo*.md",
        "*todo*.md",
        "*TODO*.md",
        "*Backlog*.md",
        "*backlog*.md",
        "*Task*.md",
        "*task*.md",
        "docs/*Todo*.md",
        "docs/*todo*.md",
        "docs/*TODO*.md",
        "docs/*Backlog*.md",
        "docs/*backlog*.md",
        "docs/*Task*.md",
        "docs/*task*.md",
        "open_tasks/**/*.md",
        "docs/open_tasks/**/*.md",
        "tasks/**/*.md",
    ]
    nearby: List[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        try:
            candidates = sorted(base.glob(pattern))
        except OSError:
            continue
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = _relative_path(base, candidate)
            if relative in seen:
                continue
            seen.add(relative)
            nearby.append(relative)
            if len(nearby) >= limit:
                return nearby
    return nearby


def _merge_dependencies(*groups: Sequence[str]) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            value = str(raw or "").strip()
            if not value:
                continue
            normalized = value.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            merged.append(value)
    return merged


def _severity_from_structured_task(task: StructuredTaskItem) -> Severity:
    priority = (task.priority or "").strip().lower()
    if priority == "p0":
        return Severity.BLOCKER
    if priority in {"p1", "high"}:
        return Severity.HIGH
    if priority in {"p2", "medium", "med"}:
        return Severity.MEDIUM
    severity = _severity_from_text(task.text or task.title)
    if task.is_blocked and severity == Severity.LOW:
        return Severity.MEDIUM
    return severity


def _severity_from_priority(priority: str | None, fallback_text: str = "") -> Severity:
    normalized = str(priority or "").strip().lower()
    if normalized == "p0":
        return Severity.BLOCKER
    if normalized in {"p1", "high"}:
        return Severity.HIGH
    if normalized in {"p2", "medium", "med"}:
        return Severity.MEDIUM
    if normalized in {"p3", "low"}:
        return Severity.LOW
    return _severity_from_text(fallback_text)


def _status_from_assignment(raw_status: str) -> WorkStatus:
    status = str(raw_status or "").strip().lower()
    if status == "in_progress":
        return WorkStatus.RUNNING
    if status == "blocked":
        return WorkStatus.BLOCKED
    if status == "review":
        return WorkStatus.RUNNING
    return WorkStatus.NEW


def _title_hash(title: str) -> str:
    return hashlib.sha1(title.strip().lower().encode("utf-8", errors="ignore")).hexdigest()


def _todo_item_from_task_ref(task_ref: Any) -> TodoItem:
    return TodoItem(
        text=str(getattr(task_ref, "title", "") or ""),
        title=str(getattr(task_ref, "title", "") or ""),
        priority=getattr(task_ref, "priority", None),
        is_blocked=bool(getattr(task_ref, "is_blocked", False)),
        blocked_by=list(getattr(task_ref, "blocked_by", []) or []),
        section=None,
    )


def from_agent_assignment(task: ActiveTask, repo_id: str) -> WorkItem:
    title = str(task.title or task.description or task.task_id).strip()[:220]
    return WorkItem(
        work_item_id=_mk_work_item_id(repo_id, "agent_assignment", f"{task.task_id}:{title}"),
        repo=repo_id,
        title=title,
        source="task",
        category=_category_from_text(f"{task.title} {task.description}".strip(), "task"),
        severity=_severity_from_priority(task.priority, f"{task.title} {task.description}".strip()),
        dependencies=[],
        constraints=list(_DEFAULT_CONSTRAINTS),
        suggested_validation=[],
        status=_status_from_assignment(task.status),
        confidence=0.9,
        metadata={
            "source_kind": "agent_assignment",
            "task_id": task.task_id,
            "description": task.description,
            "priority": task.priority,
            "assignment_status": task.status,
            "assignee_id": task.assignee_id,
            "claimed_at": task.claimed_at,
            "updated_at": task.updated_at,
            "tags": list(task.tags),
            "acceptance_criteria": list(task.acceptance_criteria),
            "note_preview": task.note_preview,
        },
    )


def from_todo_item(todo: TodoItem, repo_id: str) -> WorkItem:
    title = str(todo.title or todo.text).strip()[:220]
    return WorkItem(
        work_item_id=_mk_work_item_id(repo_id, "cross_repo_todo", title),
        repo=repo_id,
        title=title,
        source="task",
        category=_category_from_text(todo.text or title, "task"),
        severity=_severity_from_priority(todo.priority, todo.text or title),
        dependencies=list(todo.blocked_by),
        constraints=list(_DEFAULT_CONSTRAINTS),
        suggested_validation=[],
        status=WorkStatus.BLOCKED if todo.is_blocked else WorkStatus.NEW,
        confidence=0.8,
        metadata={
            "source_kind": "cross_repo_todo",
            "priority": todo.priority,
            "is_blocked": todo.is_blocked,
            "blocked_by": list(todo.blocked_by),
            "section": todo.section,
            "raw_text": todo.text,
        },
    )


def _normalize_existing_work_item(item: WorkItem, repo: ManagedRepoConfig) -> WorkItem:
    merged_dependencies = _merge_dependencies(repo.dependencies.blocked_by, item.dependencies)
    merged_constraints = item.constraints or list(_DEFAULT_CONSTRAINTS)
    validations = item.suggested_validation or list(repo.validation_commands)
    metadata = dict(item.metadata)
    metadata.setdefault("repo_purpose", repo.purpose)
    return WorkItem(
        work_item_id=item.work_item_id,
        repo=repo.repo_id,
        title=item.title[:220],
        source=item.source,
        category=item.category,
        severity=item.severity,
        dependencies=merged_dependencies,
        constraints=list(merged_constraints),
        suggested_validation=list(validations),
        status=item.status,
        confidence=item.confidence,
        run_id=item.run_id,
        metadata=metadata,
    )


def _find_assignment_ledger_path(repo: ManagedRepoConfig) -> Path | None:
    repo_key = repo.repo_id.strip().lower()
    for candidate_repo_id, ledger_path in north_star.REPO_ASSIGNMENT_LEDGERS.items():
        if str(candidate_repo_id).strip().lower() == repo_key:
            return Path(ledger_path)
    return None


def _load_agent_assignments(repo: ManagedRepoConfig) -> tuple[list[ActiveTask], Path | None]:
    ledger_path = _find_assignment_ledger_path(repo)
    if ledger_path is None:
        return [], None
    return north_star._load_assignment_ledger(ledger_path, repo.repo_id), ledger_path


def collect_repo_context(repo: ManagedRepoConfig) -> RepoContextBundle:
    root = Path(repo.root_path)
    bundle = RepoContextBundle(repo_id=repo.repo_id, root_path=str(root))

    instruction_paths = [root / rel for rel in repo.instruction_files if rel]
    task_paths, task_pattern_hits = _glob_existing(root, repo.task_sources)
    handover_paths, handover_pattern_hits = _glob_existing(root, repo.handover_locations)
    report_paths, report_pattern_hits = _glob_existing(root, repo.report_locations)
    protection_paths, protection_pattern_hits = _glob_existing(root, repo.safety_rules.protected_signal_files)

    def _record_seen(path: Path) -> None:
        value = str(path)
        if value not in bundle.files_seen:
            bundle.files_seen.append(value)

    for path in instruction_paths:
        if path.is_file():
            text = _read_text(path)
            if text:
                bundle.instruction_texts.append(text)
                _record_seen(path)

    instruction_hits = {
        str(rel): 1 if (root / rel).is_file() else 0
        for rel in repo.instruction_files
        if str(rel).strip()
    }

    for path in task_paths:
        text = _read_text(path)
        if text:
            bundle.task_texts.append(text)
            _record_seen(path)
            structured_lines = list(_extract_structured_task_lines(text))
            for line in structured_lines:
                bundle.structured_task_items.append(
                    StructuredTaskItem(
                        source_path=_relative_path(root, path),
                        text=line,
                        title=line,
                        parse_mode="json_tasks",
                    )
                )
            snapshot = parse_todo_markdown(text, repo_name=repo.repo_id, todo_path=str(path))
            for item in snapshot.items:
                bundle.structured_task_items.append(
                    StructuredTaskItem(
                        source_path=_relative_path(root, path),
                        text=item.text,
                        title=item.title,
                        priority=item.priority,
                        is_blocked=item.is_blocked,
                        blocked_by=list(item.blocked_by),
                        section=item.section,
                    )
                )
            if not structured_lines and not snapshot.items:
                for line in _extract_task_lines(text):
                    bundle.structured_task_items.append(
                        StructuredTaskItem(
                            source_path=_relative_path(root, path),
                            text=line,
                            title=line,
                            parse_mode="actionable_lines",
                        )
                    )

    for path in handover_paths:
        text = _read_text(path)
        if text:
            bundle.handover_texts.append(text)
            _record_seen(path)

    for path in report_paths:
        text = _read_text(path, max_chars=8000)
        if text:
            bundle.report_texts.append(text)
            _record_seen(path)

    for path in protection_paths:
        text = _read_text(path, max_chars=4000)
        if text:
            bundle.protected_signals.append(text)
            _record_seen(path)

    assignment_tasks, assignment_ledger_path = _load_agent_assignments(repo)
    if assignment_ledger_path is not None and assignment_ledger_path.is_file():
        _record_seen(assignment_ledger_path)
    assignment_items = [from_agent_assignment(task, repo.repo_id) for task in assignment_tasks]

    todo_repo_paths: List[str] = []
    todo_task_refs: List[Any] = []
    try:
        todo_service = get_cross_repo_todo_service()
        todo_analysis = todo_service.analyze_dependencies()
        todo_snapshot = todo_service.get_snapshot()
        todo_task_refs = list(todo_analysis.tasks_for_repo(repo.repo_id))
        for repo_snapshot in todo_snapshot.repos:
            if str(repo_snapshot.repo_name or "").strip().lower() == repo.repo_id.strip().lower():
                todo_repo_paths.extend(str(path) for path in repo_snapshot.todo_paths)
    except Exception as exc:
        LOGGER.warning("Failed cross-repo TODO analysis for %s: %s", repo.repo_id, exc)
        todo_task_refs = []
        todo_repo_paths = []
    todo_items = [from_todo_item(_todo_item_from_task_ref(task_ref), repo.repo_id) for task_ref in todo_task_refs]

    for item in assignment_items:
        bundle.prebuilt_work_items.append(item)
    for item in todo_items:
        bundle.prebuilt_work_items.append(item)

    task_parse_results = [
        {
            "path": task.source_path,
            "parse_mode": task.parse_mode,
        }
        for task in bundle.structured_task_items
    ]
    extracted_by_path: Dict[str, int] = {}
    for row in task_parse_results:
        path_key = str(row.get("path") or "")
        extracted_by_path[path_key] = extracted_by_path.get(path_key, 0) + 1

    task_relative_paths = [_relative_path(root, path) for path in task_paths]
    zero_item_files = [path for path in task_relative_paths if extracted_by_path.get(path, 0) == 0]
    task_mismatch_reason = None
    if task_relative_paths and not bundle.structured_task_items:
        task_mismatch_reason = "matched_files_without_extractable_items"
    elif repo.task_sources and not task_relative_paths:
        task_mismatch_reason = "no_matching_files"

    handover_relative_paths = [_relative_path(root, path) for path in handover_paths]
    handover_extracted_by_path: Dict[str, int] = {}
    for relative_path, text in zip(handover_relative_paths, bundle.handover_texts):
        handover_extracted_by_path[relative_path] = len(list(_extract_task_lines(text)))
    handover_zero_item_files = [path for path in handover_relative_paths if handover_extracted_by_path.get(path, 0) == 0]
    handover_mismatch_reason = None
    if handover_relative_paths and all(handover_extracted_by_path.get(path, 0) == 0 for path in handover_relative_paths):
        handover_mismatch_reason = "matched_files_without_extractable_items"
    elif repo.handover_locations and not handover_relative_paths:
        handover_mismatch_reason = "no_matching_files"

    report_relative_paths = [_relative_path(root, path) for path in report_paths]
    report_extracted_by_path: Dict[str, int] = {}
    for relative_path, text in zip(report_relative_paths, bundle.report_texts):
        report_extracted_by_path[relative_path] = len(list(_extract_task_lines(text)))
    report_zero_item_files = [path for path in report_relative_paths if report_extracted_by_path.get(path, 0) == 0]
    report_mismatch_reason = None
    if report_relative_paths and all(report_extracted_by_path.get(path, 0) == 0 for path in report_relative_paths):
        report_mismatch_reason = "matched_files_without_extractable_items"
    elif repo.report_locations and not report_relative_paths:
        report_mismatch_reason = "no_matching_files"

    bundle.source_diagnostics = {
        "instruction": _source_diagnostics(
            configured_entries=repo.instruction_files,
            matched_paths=[path for path in instruction_paths if path.is_file()],
            matched_counts=instruction_hits,
            text_blocks=len(bundle.instruction_texts),
        ),
        "task": _source_diagnostics(
            configured_entries=repo.task_sources,
            matched_paths=task_paths,
            matched_counts=task_pattern_hits,
            text_blocks=len(bundle.task_texts),
        )
        | {
            "parse_mode": "todo_markdown",
            "extracted_items": len(bundle.structured_task_items),
            "extracted_candidate_count": len(bundle.structured_task_items),
            "files_with_zero_items": zero_item_files,
            "files_with_no_candidates": zero_item_files,
            "parse_results": [
                {
                    "path": path,
                    "parse_mode": "todo_markdown",
                    "extracted_items": extracted_by_path.get(path, 0),
                }
                for path in task_relative_paths
            ],
            "mismatch_reason": task_mismatch_reason,
            "nearby_candidate_files": _find_nearby_task_candidates(root) if task_mismatch_reason else [],
        },
        "agent_assignment": {
            "configured_entries": [str(assignment_ledger_path).replace("\\", "/")] if assignment_ledger_path else [],
            "matched_files": [str(assignment_ledger_path).replace("\\", "/")] if assignment_ledger_path and assignment_ledger_path.is_file() else [],
            "matched_file_count": 1 if assignment_ledger_path and assignment_ledger_path.is_file() else 0,
            "matched_entry_count": 1 if assignment_ledger_path and assignment_ledger_path.is_file() else 0,
            "unmatched_entries": [str(assignment_ledger_path).replace("\\", "/")] if assignment_ledger_path and not assignment_ledger_path.is_file() else [],
            "text_blocks": 0,
            "extracted_candidate_count": len(assignment_items),
            "missing": assignment_ledger_path is not None and not assignment_ledger_path.is_file(),
            "empty": assignment_ledger_path is not None and assignment_ledger_path.is_file() and not assignment_items,
        },
        "cross_repo_todo": {
            "configured_entries": ["cross_repo_todo_service"],
            "matched_files": [str(path).replace("\\", "/") for path in todo_repo_paths],
            "matched_file_count": len(todo_repo_paths),
            "matched_entry_count": 1 if todo_repo_paths else 0,
            "unmatched_entries": [] if todo_repo_paths else ["cross_repo_todo_service"],
            "text_blocks": 0,
            "extracted_candidate_count": len(todo_items),
            "missing": not todo_repo_paths,
            "empty": bool(todo_repo_paths) and not todo_items,
        },
        "handover": _source_diagnostics(
            configured_entries=repo.handover_locations,
            matched_paths=handover_paths,
            matched_counts=handover_pattern_hits,
            text_blocks=len(bundle.handover_texts),
        )
        | {
            "extracted_candidate_count": sum(handover_extracted_by_path.values()),
            "files_with_no_candidates": handover_zero_item_files,
            "mismatch_reason": handover_mismatch_reason,
        },
        "report": _source_diagnostics(
            configured_entries=repo.report_locations,
            matched_paths=report_paths,
            matched_counts=report_pattern_hits,
            text_blocks=len(bundle.report_texts),
        )
        | {
            "extracted_candidate_count": sum(report_extracted_by_path.values()),
            "files_with_no_candidates": report_zero_item_files,
            "mismatch_reason": report_mismatch_reason,
        },
        "protected_signal": _source_diagnostics(
            configured_entries=repo.safety_rules.protected_signal_files,
            matched_paths=protection_paths,
            matched_counts=protection_pattern_hits,
            text_blocks=len(bundle.protected_signals),
        ),
    }

    if assignment_ledger_path is not None:
        assignment_warning = None
        if not assignment_ledger_path.is_file():
            assignment_warning = (
                f"WARNING: {repo.repo_id} agent assignment source missing: "
                f"{str(assignment_ledger_path).replace('\\', '/')}"
            )
        elif not assignment_items:
            assignment_warning = (
                f"WARNING: {repo.repo_id} agent assignment source empty: "
                f"{str(assignment_ledger_path).replace('\\', '/')}"
            )
        if assignment_warning:
            bundle.warnings.append(assignment_warning)
            LOGGER.warning(assignment_warning)

    todo_warning = None
    if not todo_repo_paths:
        todo_warning = f"WARNING: {repo.repo_id} cross-repo TODO source missing or not discovered"
    elif not todo_items:
        todo_warning = f"WARNING: {repo.repo_id} cross-repo TODO source empty"
    if todo_warning:
        bundle.warnings.append(todo_warning)
        LOGGER.warning(todo_warning)

    return bundle


def _extract_structured_task_lines(content: str) -> Iterable[str]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []
    lines: List[str] = []
    for text_key in _STRUCTURED_TEXT_KEYS:
        text_value = payload.get(text_key)
        if isinstance(text_value, str) and text_value.strip():
            lines.append(text_value.strip()[:220])

    for list_key in _STRUCTURED_LIST_KEYS:
        values = payload.get(list_key)
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, str):
                candidate = entry.strip()
                if candidate:
                    lines.append(candidate[:220])
                continue
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", "")).strip().lower()
            if status in {"completed", "closed", "done", "cancelled", "canceled"}:
                continue
            title = str(entry.get("title", "")).strip()
            task_id = str(entry.get("id", "")).strip()
            description = str(entry.get("description", "")).strip()
            message = str(entry.get("message", "")).strip()
            if not title and not task_id and not description and not message:
                continue
            candidate = title or description or message or task_id
            if task_id and task_id.lower() not in candidate.lower():
                candidate = f"[{task_id}] {candidate}".strip()
            if description and description.lower() not in candidate.lower():
                candidate = f"{candidate} - {description}".strip()
            lines.append(candidate[:220])

    deduped: List[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(line.strip())
    return deduped


def _severity_from_text(text: str) -> Severity:
    lowered = text.lower()
    if any(token in lowered for token in ["blocker", "critical", "p0", "sev0", "urgent"]):
        return Severity.BLOCKER
    if any(token in lowered for token in ["p1", "high", "failing", "error", "broken"]):
        return Severity.HIGH
    if any(token in lowered for token in ["p2", "medium", "warning"]):
        return Severity.MEDIUM
    return Severity.LOW


def _category_from_text(text: str, source: str) -> WorkCategory:
    lowered = text.lower()
    if source == "handover":
        return WorkCategory.HANDOVER
    if any(token in lowered for token in ["bug", "fix", "error", "regression", "fail"]):
        return WorkCategory.BUG
    if any(token in lowered for token in ["feature", "add", "implement"]):
        return WorkCategory.FEATURE
    if any(token in lowered for token in ["investigate", "analyze", "analysis"]):
        return WorkCategory.ANALYSIS
    return WorkCategory.MAINTENANCE


def _extract_task_lines(content: str) -> Iterable[str]:
    structured_lines = list(_extract_structured_task_lines(content))
    if structured_lines:
        yield from structured_lines
        return

    section = ""
    section_actionable = False
    in_code_block = False
    seen: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group(1).strip()
            lowered = section.lower()
            section_actionable = any(keyword in lowered for keyword in _ACTIONABLE_HEADING_KEYWORDS)
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            text = bullet.group(1).strip()
            if not text:
                continue
            candidate = f"[{section}] {text}" if section else text
        else:
            candidate = _extract_non_bullet_action_line(stripped, section_actionable)
            if not candidate:
                continue
            if section and section_actionable:
                candidate = f"[{section}] {candidate}"

        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        yield candidate


def _extract_non_bullet_action_line(line: str, section_actionable: bool) -> str | None:
    if not line or len(line) < 8:
        return None
    if line.startswith(("|", ">", "<!--")):
        return None
    if re.match(r"^[-=_]{3,}$", line):
        return None

    checkbox = _CHECKBOX_RE.match(line)
    if checkbox:
        return checkbox.group(1).strip()

    prefixed = _TASK_PREFIX_RE.match(line)
    if prefixed:
        return prefixed.group(1).strip()

    ticket_line = _TICKET_TASK_RE.match(line)
    if ticket_line:
        return ticket_line.group(1).strip()

    if section_actionable and _ACTIONABLE_SENTENCE_RE.match(line):
        return line.strip()

    return None


def _mk_work_item_id(repo_id: str, source: str, title: str) -> str:
    digest = hashlib.sha1(f"{repo_id}|{source}|{title}".encode("utf-8", errors="ignore")).hexdigest()
    return f"{repo_id.lower()}-{digest[:12]}"


def normalize_work_items(
    *,
    repo: ManagedRepoConfig,
    bundle: RepoContextBundle,
    max_items_per_source: int = 20,
) -> List[WorkItem]:
    results: List[WorkItem] = []
    seen_title_hashes: set[str] = set()

    def _append_if_new(item: WorkItem) -> None:
        key = _title_hash(item.title)
        if key in seen_title_hashes:
            return
        seen_title_hashes.add(key)
        results.append(item)

    for item in bundle.prebuilt_work_items:
        _append_if_new(_normalize_existing_work_item(item, repo))

    for task in bundle.structured_task_items[:max_items_per_source]:
        title = task.title[:220]
        _append_if_new(
            WorkItem(
                work_item_id=_mk_work_item_id(repo.repo_id, "task", f"{task.source_path}:{title}"),
                repo=repo.repo_id,
                title=title,
                source="task",
                category=_category_from_text(task.text or title, "task"),
                severity=_severity_from_structured_task(task),
                dependencies=_merge_dependencies(repo.dependencies.blocked_by, task.blocked_by),
                constraints=list(_DEFAULT_CONSTRAINTS),
                suggested_validation=list(repo.validation_commands),
                status=WorkStatus.NEW,
                confidence=0.85,
                metadata={
                    "repo_purpose": repo.purpose,
                    "source_path": task.source_path,
                    "priority": task.priority,
                    "is_blocked": task.is_blocked,
                    "blocked_by": list(task.blocked_by),
                    "section": task.section,
                    "parse_mode": task.parse_mode,
                    "raw_text": task.text,
                },
            )
        )

    for source_name, chunks in [
        ("handover", bundle.handover_texts),
        ("report", bundle.report_texts),
    ]:
        count = 0
        seen_titles: set[str] = set()
        for chunk in chunks:
            for line in _extract_task_lines(chunk):
                title = line[:220]
                dedupe_key = title.lower()
                if dedupe_key in seen_titles:
                    continue
                seen_titles.add(dedupe_key)
                work_item = WorkItem(
                    work_item_id=_mk_work_item_id(repo.repo_id, source_name, title),
                    repo=repo.repo_id,
                    title=title,
                    source=source_name,
                    category=_category_from_text(title, source_name),
                    severity=_severity_from_text(title),
                    dependencies=list(repo.dependencies.blocked_by),
                    constraints=list(_DEFAULT_CONSTRAINTS),
                    suggested_validation=list(repo.validation_commands),
                    status=WorkStatus.NEW,
                    confidence=0.65 if source_name == "report" else 0.8,
                    metadata={
                        "repo_purpose": repo.purpose,
                    },
                )
                _append_if_new(work_item)
                count += 1
                if count >= max_items_per_source:
                    break
            if count >= max_items_per_source:
                break

    return results
