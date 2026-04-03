"""Cross-repo task ledger aggregator.

This module reads agent_assignments.json ledgers from every trading-system repo and
provides:

  - A unified view of all active tasks across repos
  - Overlap detection (two tasks likely touching the same area)
  - Drift detection (tasks diverging from the North Star goal)
  - Assignment gap detection (agents idle while critical work is untracked)

The results are used by the CoordinationGuard before any new prompt is dispatched.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from automation.north_star import (
    REPO_DEPENDENCY_ORDER,
    ActiveTask,
    NorthStarContext,
    get_north_star,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OverlapWarning:
    """Two tasks that appear to be working on the same area."""

    task_a: ActiveTask
    task_b: ActiveTask
    reason: str
    severity: str  # "high" | "medium" | "low"

    def __str__(self) -> str:
        return (
            f"[{self.severity.upper()}] OVERLAP: "
            f"[{self.task_a.repo}] {self.task_a.task_id} ↔ "
            f"[{self.task_b.repo}] {self.task_b.task_id} — {self.reason}"
        )


@dataclass
class DriftWarning:
    """A task that appears to be diverging from the North Star."""

    task: ActiveTask
    reason: str
    severity: str  # "high" | "medium" | "low"

    def __str__(self) -> str:
        return (
            f"[{self.severity.upper()}] DRIFT: "
            f"[{self.task.repo}] {self.task.task_id}: {self.task.title} — {self.reason}"
        )


@dataclass
class BoundaryViolation:
    """A task that appears to violate its repo's ownership rules."""

    task: ActiveTask
    rule_broken: str
    severity: str  # "high" | "medium"

    def __str__(self) -> str:
        return (
            f"[{self.severity.upper()}] BOUNDARY VIOLATION: "
            f"[{self.task.repo}] {self.task.task_id}: {self.task.title} — {self.rule_broken}"
        )


@dataclass
class LedgerReport:
    """Complete cross-repo coordination health report."""

    generated_at: str
    all_tasks: List[ActiveTask]
    overlap_warnings: List[OverlapWarning]
    drift_warnings: List[DriftWarning]
    boundary_violations: List[BoundaryViolation]
    repos_with_ledgers: List[str]
    repos_without_ledgers: List[str]

    # ---------------------------------------------------------------------------
    # Accessors
    # ---------------------------------------------------------------------------

    @property
    def active_tasks(self) -> List[ActiveTask]:
        return [t for t in self.all_tasks if t.is_active]

    @property
    def in_progress_tasks(self) -> List[ActiveTask]:
        return [t for t in self.all_tasks if t.is_in_progress]

    @property
    def has_issues(self) -> bool:
        return bool(
            self.overlap_warnings or self.drift_warnings or self.boundary_violations
        )

    def summary_text(self) -> str:
        lines: List[str] = []
        lines.append(f"=== Cross-Repo Coordination Report  ({self.generated_at}) ===")
        lines.append(
            f"Repos: {', '.join(self.repos_with_ledgers)} — "
            f"missing ledger: {', '.join(self.repos_without_ledgers) or 'none'}"
        )
        lines.append("")
        lines.append(f"Active tasks: {len(self.active_tasks)}  |  In-progress: {len(self.in_progress_tasks)}")
        for t in self.active_tasks:
            lines.append(
                f"  [{t.priority}] [{t.repo}] {t.task_id}: {t.title[:60]}  ({t.status})"
            )
        if self.overlap_warnings:
            lines.append("")
            lines.append(f"OVERLAPS ({len(self.overlap_warnings)}):")
            for w in self.overlap_warnings:
                lines.append(f"  {w}")
        if self.drift_warnings:
            lines.append("")
            lines.append(f"DRIFT RISKS ({len(self.drift_warnings)}):")
            for w in self.drift_warnings:
                lines.append(f"  {w}")
        if self.boundary_violations:
            lines.append("")
            lines.append(f"BOUNDARY VIOLATIONS ({len(self.boundary_violations)}):")
            for v in self.boundary_violations:
                lines.append(f"  {v}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Keyword extraction helpers
# ---------------------------------------------------------------------------

# Area keywords: maps a normalized key to a set of trigger words.
# If two tasks share an area key, they are flagged as potential overlaps.
_AREA_KEYWORDS: Dict[str, FrozenSet[str]] = {
    "seconds_model": frozenset(
        ["seconds model", "seconds-model", "seconds bar", "seconds training", "intraday model"]
    ),
    "gap_opener": frozenset(
        ["gap opener", "gap-opener", "gap_opener", "pre-market ranking", "gapopener"]
    ),
    "l2_orderbook": frozenset(
        ["level 2", "l2", "mbp", "order book", "orderbook", "market by price"]
    ),
    "ib_gateway": frozenset(
        ["ib gateway", "ibkr", "interactive brokers", "gateway lifecycle", "headless gateway"]
    ),
    "data_pipeline": frozenset(
        ["data pipeline", "data manager", "data_manager", "parquet", "bars download", "manifest"]
    ),
    "contracts_schema": frozenset(
        ["schema", "manifest.schema", "promotion rule", "json-logic", "fixture", "contract"]
    ),
    "paper_trading": frozenset(
        ["paper trading", "paper-trading", "shadow trading", "paper mode", "paper_trading"]
    ),
    "model_export": frozenset(
        ["model export", "manifest generation", "model promotion", "export manifest"]
    ),
    "wandb_experiment": frozenset(
        ["wandb", "weights & biases", "experiment tracking", "sweep", "w&b"]
    ),
    "ib_conn": frozenset(
        ["ib_conn", "ib connection", "port probe", "fallback client", "fake client"]
    ),
}


def _text_areas(text: str) -> Set[str]:
    """Return the set of area keys triggered by the given text (lower-case)."""
    text_lower = text.lower()
    matched: Set[str] = set()
    for area, keywords in _AREA_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            matched.add(area)
    return matched


def _task_areas(task: ActiveTask) -> Set[str]:
    combined = " ".join(
        filter(None, [task.title, task.description, " ".join(task.tags)])
    )
    return _text_areas(combined)


# ---------------------------------------------------------------------------
# North Star alignment scoring
# ---------------------------------------------------------------------------

# Keywords strongly associated with the current North Star goal
_NORTH_STAR_KEYWORDS: FrozenSet[str] = frozenset(
    [
        "seconds paper", "paper trading", "paper-trading", "production ready",
        "prod readiness", "seconds model", "seconds-model", "signal gate",
        "promotion gate", "go/no-go", "trading pipeline", "model pipeline",
        "soak", "shadow gate", "paper soak", "risk check", "safety check",
        "seconds bar", "intraday", "promote model", "model promotion",
        "data pipeline", "data acquisition", "ib gateway", "gateway lifecycle",
        "ibkr", "backfill", "manifest", "model manifest", "export manifest",
    ]
)

# Keywords that suggest rabbit-hole / out-of-scope work
_RABBIT_HOLE_KEYWORDS: FrozenSet[str] = frozenset(
    [
        "refactor", "rename", "cosmetic", "cleanup docs", "tidy", "reorganise",
        "reorganize", "style fix", "formatting", "linting only", "typo",
        "whitespace", "archived", "legacy migration", "remove old",
        "delete unused", "deprecate", "internal tooling", "dev tooling",
        "build system", "ci pipeline", "github actions", "pre-commit",
        "upgrade dependencies", "bump version", "release notes",
    ]
)


def _north_star_score(task: ActiveTask, north_star: NorthStarContext) -> float:
    """
    Return a 0.0–1.0 alignment score for a task against the current North Star goal.

    0.0 = no alignment or rabbit hole
    1.0 = clearly contributes to the primary goal
    """
    text = " ".join(
        filter(None, [task.title, task.description, " ".join(task.acceptance_criteria)])
    ).lower()

    # Boost for North Star keywords
    ns_matches = sum(1 for kw in _NORTH_STAR_KEYWORDS if kw in text)
    rabbit_matches = sum(1 for kw in _RABBIT_HOLE_KEYWORDS if kw in text)

    # Also try to match words from the primary goal description
    goal_words = set(re.findall(r"\w{5,}", north_star.primary_goal.lower()))
    goal_word_matches = sum(1 for w in goal_words if w in text)

    score = min(1.0, (ns_matches * 0.15) + (goal_word_matches * 0.07))
    score -= rabbit_matches * 0.10
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------


def _detect_overlaps(tasks: List[ActiveTask]) -> List[OverlapWarning]:
    """Compare every pair of active tasks for area overlap."""
    active = [t for t in tasks if t.is_active]
    warnings: List[OverlapWarning] = []

    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]

            # Same repo + same area is high severity; cross-repo is medium
            areas_a = _task_areas(a)
            areas_b = _task_areas(b)
            shared = areas_a & areas_b
            if not shared:
                continue

            severity = "high" if a.repo == b.repo else "medium"
            reason = f"both touch: {', '.join(sorted(shared))}"
            warnings.append(OverlapWarning(task_a=a, task_b=b, reason=reason, severity=severity))

    return warnings


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def _detect_drift(
    tasks: List[ActiveTask], north_star: NorthStarContext
) -> List[DriftWarning]:
    """Flag tasks with low North Star alignment."""
    warnings: List[DriftWarning] = []
    for task in tasks:
        if not task.is_active:
            continue

        # P0/P1 tasks are by definition aligned (they came from the same ledger)
        if task.priority in ("P0",):
            continue

        score = _north_star_score(task, north_star)
        if score < 0.05:
            warnings.append(
                DriftWarning(
                    task=task,
                    reason=(
                        f"no keywords matching current North Star goal "
                        f"(score={score:.2f}). Verify this task actually advances: "
                        f'"{north_star.primary_goal[:80]}"'
                    ),
                    severity="medium",
                )
            )
        elif score < 0.10 and task.priority in ("P2", "P3"):
            warnings.append(
                DriftWarning(
                    task=task,
                    reason=f"low alignment score ({score:.2f}) for {task.priority} task; review priority",
                    severity="low",
                )
            )
    return warnings


# ---------------------------------------------------------------------------
# Boundary violation detection
# ---------------------------------------------------------------------------

_BOUNDARY_RULES: Dict[str, List[Tuple[str, str]]] = {
    # repo → [(must_not_keyword_pattern, human_reason), ...]
    "TF": [
        (r"order exec|position siz|broker connect|ib gateway|live trad|ibkr", "TF must not touch execution/broker code"),
        (r"contracts/schemas|manifest\.schema\.json|promotion\.rule", "TF must not modify contracts schemas directly"),
    ],
    "Trading": [
        (r"model train|feature engineer|experiment track|wandb|hyperparameter", "Trading must not contain ML training code"),
        (r"contracts/schemas|manifest\.schema\.json|promotion\.rule", "Trading must not modify contracts schemas directly"),
    ],
    "contracts": [
        (r"model code|trading code|notebook|general.purpose script", "contracts must stay governance-only"),
        (r"run_trading|headless_gateway|ib_conn|data_manager", "contracts must not touch runtime execution code"),
    ],
}


def _detect_boundary_violations(tasks: List[ActiveTask]) -> List[BoundaryViolation]:
    violations: List[BoundaryViolation] = []
    for task in tasks:
        if not task.is_active:
            continue
        rules = _BOUNDARY_RULES.get(task.repo, [])
        text = " ".join(
            filter(None, [task.title, task.description, " ".join(task.tags)])
        ).lower()
        for pattern, reason in rules:
            if re.search(pattern, text):
                violations.append(
                    BoundaryViolation(task=task, rule_broken=reason, severity="medium")
                )
                break  # one violation per task is enough
    return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_ledger_report(
    north_star: Optional[NorthStarContext] = None,
) -> LedgerReport:
    """
    Build a full cross-repo coordination report.

    Parameters
    ----------
    north_star:
        Pre-loaded NorthStarContext. If None, loads via get_north_star().
    """
    ns = north_star or get_north_star()
    all_tasks = list(ns.active_tasks)

    # Track which repos contributed
    repos_with = [r for r in REPO_DEPENDENCY_ORDER if any(t.repo == r for t in all_tasks)]
    repos_without = [r for r in REPO_DEPENDENCY_ORDER if r not in repos_with]

    return LedgerReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        all_tasks=all_tasks,
        overlap_warnings=_detect_overlaps(all_tasks),
        drift_warnings=_detect_drift(all_tasks, ns),
        boundary_violations=_detect_boundary_violations(all_tasks),
        repos_with_ledgers=repos_with,
        repos_without_ledgers=repos_without,
    )


# Singleton cache -----------------------------------------------------------
_cached_report: Optional[LedgerReport] = None
_report_loaded_at: Optional[datetime] = None
_REPORT_CACHE_TTL = int(os.environ.get("LEDGER_REPORT_CACHE_TTL_SECONDS", "120"))


def get_ledger_report(*, force_refresh: bool = False) -> LedgerReport:
    """Return a (possibly cached) LedgerReport."""
    global _cached_report, _report_loaded_at
    now = datetime.now(timezone.utc)
    stale = (
        _cached_report is None
        or _report_loaded_at is None
        or (now - _report_loaded_at).total_seconds() > _REPORT_CACHE_TTL
    )
    if force_refresh or stale:
        try:
            _cached_report = build_ledger_report()
        except Exception:
            if _cached_report is not None:
                return _cached_report
            _cached_report = LedgerReport(
                generated_at=datetime.now(timezone.utc).isoformat(),
                all_tasks=[],
                overlap_warnings=[],
                drift_warnings=[],
                boundary_violations=[],
                repos_with_ledgers=[],
                repos_without_ledgers=list(REPO_DEPENDENCY_ORDER),
            )
        _report_loaded_at = now
    assert _cached_report is not None
    return _cached_report
