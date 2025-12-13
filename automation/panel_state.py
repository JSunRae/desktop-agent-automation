"""Panel state types and lightweight helpers.

This module is intentionally UI-automation-free so it can be imported by both
core tracking logic and higher-level workflows without circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from automation.config import VSCODE_TITLE_SUFFIX
from automation.response_parser import ResponseCategory


# VS Code window titles usually end with " - Visual Studio Code" but can also use
# a shorter " - VS Code" suffix. Deduplicate in case both strings are identical.
WINDOW_TITLE_SUFFIXES: tuple[str, ...] = tuple(
    dict.fromkeys([suffix for suffix in (VSCODE_TITLE_SUFFIX, " - VS Code") if suffix])
)


# Transcript snapshot controls keep panel_state.json compact while still
# providing enough context for follow-up automation.
TRANSCRIPT_PREVIEW_CHARS = 160
TRANSCRIPT_HASH_LEN = 12
TRANSCRIPT_MAX_SNAPSHOTS = 4
TRANSCRIPT_FILTER_PLACEHOLDER = "<filtered>"
TRANSCRIPT_KIND_SEED_PROMPT = "seed_prompt"
TRANSCRIPT_KIND_COMPLETION = "completion"
TRANSCRIPT_KIND_REVIEW = "review_directive"


class PanelStatus(Enum):
    """Status of a tracked panel."""

    RUNNING = "running"
    WAITING_ALLOW = "waiting_allow"
    RATE_LIMITED = "rate_limited"
    IDLE = "idle"
    FINISHED = "finished"
    COMPLETED = "completed"
    STALE = "stale"
    NEEDS_INPUT = "needs_input"
    ERROR = "error"


class IdleReason(Enum):
    """Why a panel is idle (has Send button instead of Cancel)."""

    WAITING_ALLOW = "waiting_allow"
    RATE_LIMITED_BUTTON = "rate_limited_button"
    RATE_LIMITED_NO_BUTTON = "rate_limited_no_button"
    POSSIBLY_FINISHED = "possibly_finished"
    AWAITING_USER = "awaiting_user"


def extract_repo_name_from_title(window_title: str) -> Optional[str]:
    """Extract the repo identifier from a VS Code window title."""
    if not window_title:
        return None
    normalized = window_title.strip()
    for suffix in WINDOW_TITLE_SUFFIXES:
        if suffix and normalized.endswith(suffix):
            core = normalized[: -len(suffix)]
            parts = [segment.strip() for segment in core.split(" - ") if segment.strip()]
            if parts:
                return parts[-1]
    return None


def _preview_transcript_text(text: str) -> str:
    cleaned = text.strip().replace("\r", "")
    if len(cleaned) <= TRANSCRIPT_PREVIEW_CHARS:
        return cleaned
    return f"{cleaned[: TRANSCRIPT_PREVIEW_CHARS - 3]}..."


@dataclass
class TranscriptSnapshot:
    """Compact snapshot of a prompt or completion transcript."""

    kind: str
    timestamp: datetime
    content_hash: str
    preview: Optional[str] = None
    filtered: bool = False
    length: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "timestamp": self.timestamp.isoformat(),
            "content_hash": self.content_hash,
            "preview": self.preview,
            "filtered": self.filtered,
            "length": self.length,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptSnapshot":
        ts_value = data.get("timestamp")
        timestamp = datetime.fromisoformat(ts_value) if ts_value else datetime.now()
        return cls(
            kind=data.get("kind", TRANSCRIPT_KIND_SEED_PROMPT),
            timestamp=timestamp,
            content_hash=data.get("content_hash", ""),
            preview=data.get("preview"),
            filtered=bool(data.get("filtered", False)),
            length=int(data.get("length", 0)),
        )


class QualityStatus(Enum):
    """Quality classification for a panel's transcript."""

    COMPLETED = "COMPLETED"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    UNKNOWN = "UNKNOWN"


@dataclass
class QualityComponentScores:
    """Breakdown of the panel quality score."""

    code_completeness: float = 0.0
    test_coverage: float = 0.0
    error_free_execution: float = 0.0
    documentation: float = 0.0
    prompt_alignment: float = 0.0

    def to_dict(self) -> dict:
        return {
            "code_completeness": self.code_completeness,
            "test_coverage": self.test_coverage,
            "error_free_execution": self.error_free_execution,
            "documentation": self.documentation,
            "prompt_alignment": self.prompt_alignment,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "QualityComponentScores":
        if not data:
            return cls()
        return cls(
            code_completeness=float(data.get("code_completeness", 0.0)),
            test_coverage=float(data.get("test_coverage", 0.0)),
            error_free_execution=float(data.get("error_free_execution", 0.0)),
            documentation=float(data.get("documentation", 0.0)),
            prompt_alignment=float(data.get("prompt_alignment", 0.0)),
        )


@dataclass
class PanelQualityAssessment:
    """Latest quality assessment derived from transcripts."""

    status: QualityStatus = QualityStatus.UNKNOWN
    score: float = 0.0
    confidence: float = 0.0
    component_scores: QualityComponentScores = field(default_factory=QualityComponentScores)
    issues: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    needs_human_review: bool = False
    last_evaluated: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "score": self.score,
            "confidence": self.confidence,
            "component_scores": self.component_scores.to_dict(),
            "issues": list(self.issues),
            "flags": list(self.flags),
            "notes": self.notes,
            "needs_human_review": self.needs_human_review,
            "last_evaluated": self.last_evaluated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["PanelQualityAssessment"]:
        if not data:
            return None
        status_val = data.get("status") or QualityStatus.UNKNOWN.value
        try:
            status = QualityStatus(status_val)
        except ValueError:
            status = QualityStatus.UNKNOWN

        timestamp_str = data.get("last_evaluated")
        timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now()

        return cls(
            status=status,
            score=float(data.get("score", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            component_scores=QualityComponentScores.from_dict(data.get("component_scores")),
            issues=list(data.get("issues", [])),
            flags=list(data.get("flags", [])),
            notes=data.get("notes"),
            needs_human_review=bool(data.get("needs_human_review", False)),
            last_evaluated=timestamp,
        )


@dataclass
class QualityTrendEntry:
    """Historical record of quality scoring for reporting."""

    timestamp: datetime
    status: QualityStatus
    score: float
    issues: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "score": self.score,
            "issues": list(self.issues),
            "flags": list(self.flags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QualityTrendEntry":
        status_val = data.get("status") or QualityStatus.UNKNOWN.value
        try:
            status = QualityStatus(status_val)
        except ValueError:
            status = QualityStatus.UNKNOWN

        ts_value = data.get("timestamp")
        timestamp = datetime.fromisoformat(ts_value) if ts_value else datetime.now()

        return cls(
            timestamp=timestamp,
            status=status,
            score=float(data.get("score", 0.0)),
            issues=list(data.get("issues", [])),
            flags=list(data.get("flags", [])),
        )


@dataclass
class PanelState:
    """State of a single panel we're tracking."""

    window_title: str
    panel_id: str
    first_seen: datetime
    last_allow_click: datetime
    last_output_change: datetime
    last_scanned: datetime = field(default_factory=datetime.now)
    last_allow_check: datetime = field(default_factory=datetime.now)
    last_output_sample: str = ""
    last_output_hash: str = ""
    status: PanelStatus = PanelStatus.IDLE
    is_running: bool = False
    idle_reason: Optional[IdleReason] = None
    last_response_category: Optional[ResponseCategory] = None
    last_response_confidence: float = 0.0
    last_response_evidence: List[str] = field(default_factory=list)
    last_response_secondary_categories: List[ResponseCategory] = field(default_factory=list)
    sent_completion_check: bool = False
    sent_next_steps_response: bool = False
    times_checked: int = 0
    sent_please_continue: bool = False
    seeded_prompt: bool = False
    assigned_prompt_index: Optional[int] = None
    assigned_prompt_id: Optional[str] = None
    assigned_prompt_text: Optional[str] = None
    repo_name: Optional[str] = None
    assignment_time: Optional[datetime] = None
    assigned_task_id: Optional[str] = None
    assigned_task_name: Optional[str] = None
    assignment_batch_id: Optional[str] = None
    assignment_source: Optional[str] = None
    assigned_model_label: Optional[str] = None
    assignment_attempts: int = 0
    assignment_successes: int = 0
    assignment_failures: int = 0
    last_assignment_outcome_id: Optional[str] = None
    priority_score: float = 0.0
    priority_components: Dict[str, float] = field(default_factory=dict)
    transcript_snapshots: List[TranscriptSnapshot] = field(default_factory=list)
    last_seed_prompt_text: Optional[str] = None
    last_review_action: Optional[str] = None
    last_review_message: Optional[str] = None
    quality_assessment: Optional[PanelQualityAssessment] = None
    quality_history: List[QualityTrendEntry] = field(default_factory=list)
    needs_human_review: bool = False
    transcript_issue_tags: List[str] = field(default_factory=list)
    transcript_issue_summary: Optional[str] = None
    last_transcript_analysis: Optional[datetime] = None
    # Prompt seeding retry + failure tracking
    needs_retry: bool = False
    seed_retry_count: int = 0
    seed_last_failure_reason: Optional[str] = None
    seed_next_retry_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "window_title": self.window_title,
            "panel_id": self.panel_id,
            "first_seen": self.first_seen.isoformat(),
            "last_allow_click": self.last_allow_click.isoformat(),
            "last_output_change": self.last_output_change.isoformat(),
            "last_scanned": self.last_scanned.isoformat(),
            "last_allow_check": self.last_allow_check.isoformat(),
            "last_output_sample": self.last_output_sample,
            "last_output_hash": self.last_output_hash,
            "status": self.status.value,
            "is_running": self.is_running,
            "idle_reason": self.idle_reason.value if self.idle_reason else None,
            "last_response_category": self.last_response_category.value if self.last_response_category else None,
            "last_response_confidence": self.last_response_confidence,
            "last_response_evidence": self.last_response_evidence,
            "last_response_secondary_categories": [c.value for c in self.last_response_secondary_categories],
            "sent_completion_check": self.sent_completion_check,
            "sent_next_steps_response": self.sent_next_steps_response,
            "sent_please_continue": self.sent_please_continue,
            "times_checked": self.times_checked,
            "seeded_prompt": self.seeded_prompt,
            "assigned_prompt_index": self.assigned_prompt_index,
            "assigned_prompt_id": self.assigned_prompt_id,
            "assigned_prompt_text": self.assigned_prompt_text,
            "repo_name": self.repo_name,
            "assignment_time": self.assignment_time.isoformat() if self.assignment_time else None,
            "assigned_task_id": self.assigned_task_id,
            "assigned_task_name": self.assigned_task_name,
            "assignment_batch_id": self.assignment_batch_id,
            "assignment_source": self.assignment_source,
            "assigned_model_label": self.assigned_model_label,
            "assignment_attempts": self.assignment_attempts,
            "assignment_successes": self.assignment_successes,
            "assignment_failures": self.assignment_failures,
            "last_assignment_outcome_id": self.last_assignment_outcome_id,
            "priority_score": self.priority_score,
            "priority_components": self.priority_components,
            "transcript_snapshots": [snap.to_dict() for snap in self.transcript_snapshots],
            "last_seed_prompt_text": self.last_seed_prompt_text,
            "last_review_action": self.last_review_action,
            "last_review_message": self.last_review_message,
            "quality_assessment": self.quality_assessment.to_dict() if self.quality_assessment else None,
            "quality_history": [entry.to_dict() for entry in self.quality_history],
            "needs_human_review": self.needs_human_review,
            "transcript_issue_tags": self.transcript_issue_tags,
            "transcript_issue_summary": self.transcript_issue_summary,
            "last_transcript_analysis": self.last_transcript_analysis.isoformat() if self.last_transcript_analysis else None,
            "needs_retry": self.needs_retry,
            "seed_retry_count": self.seed_retry_count,
            "seed_last_failure_reason": self.seed_last_failure_reason,
            "seed_next_retry_at": self.seed_next_retry_at.isoformat() if self.seed_next_retry_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PanelState":
        idle_reason_val = data.get("idle_reason")
        idle_reason = IdleReason(idle_reason_val) if idle_reason_val else None

        last_response_category: Optional[ResponseCategory] = None
        last_response_category_val = data.get("last_response_category")
        if last_response_category_val:
            try:
                last_response_category = ResponseCategory(last_response_category_val)
            except ValueError:
                last_response_category = None

        secondary_categories: List[ResponseCategory] = []
        for value in data.get("last_response_secondary_categories", []) or []:
            try:
                secondary_categories.append(ResponseCategory(value))
            except ValueError:
                continue

        snapshot_dicts = data.get("transcript_snapshots", []) or []
        transcript_snapshots: List[TranscriptSnapshot] = []
        for raw_snapshot in snapshot_dicts:
            try:
                transcript_snapshots.append(TranscriptSnapshot.from_dict(raw_snapshot))
            except Exception:
                continue

        quality_assessment = PanelQualityAssessment.from_dict(data.get("quality_assessment"))
        raw_quality_history = data.get("quality_history", []) or []
        quality_history: List[QualityTrendEntry] = []
        for raw_entry in raw_quality_history:
            try:
                quality_history.append(QualityTrendEntry.from_dict(raw_entry))
            except Exception:
                continue

        last_scanned_str = data.get("last_scanned")
        if last_scanned_str:
            last_scanned = datetime.fromisoformat(last_scanned_str)
        else:
            last_scanned = datetime.fromisoformat(data["last_allow_click"])

        last_allow_check_str = data.get("last_allow_check")
        if last_allow_check_str:
            last_allow_check = datetime.fromisoformat(last_allow_check_str)
        else:
            last_allow_check = last_scanned

        needs_retry = bool(data.get("needs_retry", False))
        seed_retry_count = int(data.get("seed_retry_count", 0) or 0)
        seed_last_failure_reason = data.get("seed_last_failure_reason")
        seed_next_retry_raw = data.get("seed_next_retry_at")
        seed_next_retry_at = None
        if seed_next_retry_raw:
            try:
                seed_next_retry_at = datetime.fromisoformat(seed_next_retry_raw)
            except Exception:
                seed_next_retry_at = None

        return cls(
            window_title=data["window_title"],
            panel_id=data["panel_id"],
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_allow_click=datetime.fromisoformat(data["last_allow_click"]),
            last_output_change=datetime.fromisoformat(data["last_output_change"]),
            last_scanned=last_scanned,
            last_allow_check=last_allow_check,
            last_output_sample=data.get("last_output_sample", ""),
            last_output_hash=data.get("last_output_hash", ""),
            status=PanelStatus(data.get("status", "idle").replace("live", "running")),
            is_running=data.get("is_running", False),
            idle_reason=idle_reason,
            last_response_category=last_response_category,
            last_response_confidence=float(data.get("last_response_confidence", 0.0)),
            last_response_evidence=list(data.get("last_response_evidence") or []),
            last_response_secondary_categories=secondary_categories,
            sent_completion_check=data.get("sent_completion_check", False),
            sent_next_steps_response=data.get("sent_next_steps_response", False),
            sent_please_continue=data.get("sent_please_continue", False),
            times_checked=data.get("times_checked", 0),
            seeded_prompt=data.get("seeded_prompt", False),
            assigned_prompt_index=data.get("assigned_prompt_index"),
            assigned_prompt_id=data.get("assigned_prompt_id"),
            assigned_prompt_text=data.get("assigned_prompt_text"),
            repo_name=data.get("repo_name"),
            assignment_time=datetime.fromisoformat(data["assignment_time"]) if data.get("assignment_time") else None,
            assigned_task_id=data.get("assigned_task_id"),
            assigned_task_name=data.get("assigned_task_name"),
            assignment_batch_id=data.get("assignment_batch_id"),
            assignment_source=data.get("assignment_source"),
            assigned_model_label=data.get("assigned_model_label"),
            assignment_attempts=int(data.get("assignment_attempts", 0) or 0),
            assignment_successes=int(data.get("assignment_successes", 0) or 0),
            assignment_failures=int(data.get("assignment_failures", 0) or 0),
            last_assignment_outcome_id=data.get("last_assignment_outcome_id"),
            priority_score=float(data.get("priority_score", 0.0) or 0.0),
            priority_components=dict(data.get("priority_components", {}) or {}),
            transcript_snapshots=transcript_snapshots,
            last_seed_prompt_text=data.get("last_seed_prompt_text"),
            last_review_action=data.get("last_review_action"),
            last_review_message=data.get("last_review_message"),
            quality_assessment=quality_assessment,
            quality_history=quality_history,
            needs_human_review=bool(data.get("needs_human_review", False)),
            transcript_issue_tags=list(data.get("transcript_issue_tags") or []),
            transcript_issue_summary=data.get("transcript_issue_summary"),
            last_transcript_analysis=datetime.fromisoformat(data["last_transcript_analysis"]) if data.get("last_transcript_analysis") else None,
            needs_retry=needs_retry,
            seed_retry_count=seed_retry_count,
            seed_last_failure_reason=seed_last_failure_reason,
            seed_next_retry_at=seed_next_retry_at,
        )
