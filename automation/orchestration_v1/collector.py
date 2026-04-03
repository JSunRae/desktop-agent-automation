from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List, Sequence

from automation.orchestration_v1.models import (
    ManagedRepoConfig,
    RepoContextBundle,
    Severity,
    WorkCategory,
    WorkItem,
    WorkStatus,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")


def _read_text(path: Path, max_chars: int = 12000) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return raw[:max_chars] if len(raw) > max_chars else raw


def _glob_existing(base: Path, patterns: Sequence[str], limit: int = 40) -> List[Path]:
    found: List[Path] = []
    seen: set[str] = set()
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
            if len(found) >= limit:
                return found
    return found


def collect_repo_context(repo: ManagedRepoConfig) -> RepoContextBundle:
    root = Path(repo.root_path)
    bundle = RepoContextBundle(repo_id=repo.repo_id, root_path=str(root))

    instruction_paths = [root / rel for rel in repo.instruction_files if rel]
    task_paths = _glob_existing(root, repo.task_sources)
    handover_paths = _glob_existing(root, repo.handover_locations)
    report_paths = _glob_existing(root, repo.report_locations)
    protection_paths = _glob_existing(root, repo.safety_rules.protected_signal_files)

    for path in instruction_paths:
        if path.is_file():
            text = _read_text(path)
            if text:
                bundle.instruction_texts.append(text)
                bundle.files_seen.append(str(path))

    for path in task_paths:
        text = _read_text(path)
        if text:
            bundle.task_texts.append(text)
            bundle.files_seen.append(str(path))

    for path in handover_paths:
        text = _read_text(path)
        if text:
            bundle.handover_texts.append(text)
            bundle.files_seen.append(str(path))

    for path in report_paths:
        text = _read_text(path, max_chars=8000)
        if text:
            bundle.report_texts.append(text)
            bundle.files_seen.append(str(path))

    for path in protection_paths:
        text = _read_text(path, max_chars=4000)
        if text:
            bundle.protected_signals.append(text)
            bundle.files_seen.append(str(path))

    return bundle


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
    section = ""
    for line in content.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group(1).strip()
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        text = bullet.group(1).strip()
        if not text:
            continue
        if section:
            yield f"[{section}] {text}"
        else:
            yield text


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

    for source_name, chunks in [
        ("task", bundle.task_texts),
        ("handover", bundle.handover_texts),
        ("report", bundle.report_texts),
    ]:
        count = 0
        for chunk in chunks:
            for line in _extract_task_lines(chunk):
                title = line[:220]
                work_item = WorkItem(
                    work_item_id=_mk_work_item_id(repo.repo_id, source_name, title),
                    repo=repo.repo_id,
                    title=title,
                    source=source_name,
                    category=_category_from_text(title, source_name),
                    severity=_severity_from_text(title),
                    dependencies=list(repo.dependencies.blocked_by),
                    constraints=[
                        "respect_repo_local_instructions",
                        "do_not_interrupt_protected_processes",
                        "operate_within_managed_repo_boundary",
                    ],
                    suggested_validation=list(repo.validation_commands),
                    status=WorkStatus.NEW,
                    confidence=0.65 if source_name == "report" else 0.8,
                    metadata={
                        "repo_purpose": repo.purpose,
                    },
                )
                results.append(work_item)
                count += 1
                if count >= max_items_per_source:
                    break
            if count >= max_items_per_source:
                break

    return results
