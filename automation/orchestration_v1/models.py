from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkCategory(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    MAINTENANCE = "maintenance"
    ANALYSIS = "analysis"
    HANDOVER = "handover"


class Severity(str, Enum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WorkStatus(str, Enum):
    NEW = "new"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    STOPPED = "stopped"


class WorkerOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class RepoSafetyRules:
    protected_process_patterns: List[str] = field(default_factory=list)
    protected_signal_files: List[str] = field(default_factory=list)
    allow_paths: List[str] = field(default_factory=list)
    requires_explicit_approval_for: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepoDependencyRules:
    blocked_by: List[str] = field(default_factory=list)
    follow_up_targets: List[str] = field(default_factory=list)
    source_of_truth_for: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ManagedRepoConfig:
    repo_id: str
    root_path: str
    purpose: str
    instruction_files: List[str]
    task_sources: List[str]
    handover_locations: List[str]
    report_locations: List[str]
    validation_commands: List[str]
    safety_rules: RepoSafetyRules
    dependencies: RepoDependencyRules


@dataclass(frozen=True)
class WorkspaceConstraints:
    max_active_workers_total: int = 2
    max_active_workers_per_repo: int = 1
    loop_retry_limit: int = 3
    respect_repo_boundaries: bool = True
    prefer_structured_sources: bool = True


@dataclass(frozen=True)
class ManagedWorkspaceRegistry:
    workspace_id: str
    description: str
    version: int
    global_constraints: WorkspaceConstraints
    repos: List[ManagedRepoConfig]


@dataclass
class RepoContextBundle:
    repo_id: str
    root_path: str
    instruction_texts: List[str] = field(default_factory=list)
    task_texts: List[str] = field(default_factory=list)
    handover_texts: List[str] = field(default_factory=list)
    report_texts: List[str] = field(default_factory=list)
    protected_signals: List[str] = field(default_factory=list)
    files_seen: List[str] = field(default_factory=list)


@dataclass
class WorkItem:
    work_item_id: str
    repo: str
    title: str
    source: str
    category: WorkCategory
    severity: Severity
    dependencies: List[str]
    constraints: List[str]
    suggested_validation: List[str]
    status: WorkStatus
    confidence: float
    run_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationRun:
    command: str
    result: str
    notes: str = ""


@dataclass
class ChangedFile:
    path: str
    reason: str


@dataclass
class WorkerCompletionReport:
    status: WorkerOutcome
    summary: str
    files_changed: List[ChangedFile] = field(default_factory=list)
    tests_validation_run: List[ValidationRun] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    next_recommended_actions: List[str] = field(default_factory=list)
    handover_report_path: Optional[str] = None
    raw_text: str = ""


@dataclass
class OrchestrationDecision:
    action: str
    reason: str
    create_follow_up: bool = False
    follow_up_repo: Optional[str] = None


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    repo: str
    work_item_id: str
    status: str


@dataclass
class OrchestrationCycleResult:
    run_id: Optional[str]
    selected_work_item: Optional[WorkItem]
    decision: Optional[OrchestrationDecision]
    report: Optional[WorkerCompletionReport]
    notes: List[str] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
