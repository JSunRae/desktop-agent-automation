"""Coordination guard: pre-dispatch safety check for all agent tasks.

Before the orchestrator dispatches a new prompt to any panel, CoordinationGuard
evaluates three questions:

  1. OVERLAP – Is this work already being done by another agent in any repo?
  2. DRIFT   – Does this task actually advance the North Star goal?
  3. ROUTING – Is this the right repo for this kind of work?

If the answer to any check is "no", the guard returns a CoordinationDecision
that tells the orchestrator to block, redirect, or proceed with a caveat.

Usage::

    guard = CoordinationGuard()
    decision = guard.evaluate(prompt_text, target_repo="TF")
    if decision.should_block:
        print(decision.block_reason)
    else:
        # safe to dispatch, inject decision.context_prefix into the prompt
        final_prompt = decision.context_prefix + "\\n\\n" + prompt_text
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from automation.north_star import (
    REPO_DEPENDENCY_ORDER,
    NorthStarContext,
    RepoRole,
    get_north_star,
)
from automation.repo_task_ledger import (
    LedgerReport,
    _north_star_score,
    _text_areas,
    get_ledger_report,
)

# ---------------------------------------------------------------------------
# Enums / result types
# ---------------------------------------------------------------------------


class DecisionOutcome(str, Enum):
    PROCEED = "proceed"              # Safe to dispatch as-is
    PROCEED_WITH_CONTEXT = "proceed_with_context"  # Dispatch but inject extra warnings
    REDIRECT = "redirect"            # Wrong repo — redirect to correct one
    BLOCK = "block"                  # Clear conflict — do not dispatch


@dataclass
class CoordinationDecision:
    """Result of the guard evaluation."""

    outcome: DecisionOutcome
    target_repo: Optional[str]

    # Human-readable explanation for any block/redirect
    block_reason: Optional[str] = None
    redirect_to_repo: Optional[str] = None
    cautions: List[str] = field(default_factory=list)

    # North Star context prefix to prepend to the prompt
    context_prefix: str = ""

    # Alignment score of the candidate prompt against the North Star (0-1)
    alignment_score: float = 0.0

    @property
    def should_block(self) -> bool:
        return self.outcome == DecisionOutcome.BLOCK

    @property
    def should_redirect(self) -> bool:
        return self.outcome == DecisionOutcome.REDIRECT

    def summary(self) -> str:
        parts = [f"[{self.outcome.value.upper()}]"]
        if self.block_reason:
            parts.append(f"block: {self.block_reason}")
        if self.redirect_to_repo:
            parts.append(f"redirect-to: {self.redirect_to_repo}")
        if self.cautions:
            parts.append("cautions: " + "; ".join(self.cautions))
        parts.append(f"alignment={self.alignment_score:.2f}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Routing classifier
# ---------------------------------------------------------------------------

# Simple keyword → repo heuristic (used when target_repo is unknown or to validate)
_ROUTING_SIGNALS: dict[str, list[str]] = {
    "contracts": [
        "schema", "json schema", "manifest.schema", "promotion rule", "fixture",
        "json-logic", "checksum", "governance", "versioning",
    ],
    "TF": [
        "model train", "feature engineer", "label engineer", "wandb", "w&b", "experiment",
        "hyperparameter", "sweep", "keras", "tensorflow", "torch", "model eval",
        "model export", "ml model", "signal model", "gap opener model",
    ],
    "Trading": [
        "ib gateway", "ibkr", "interactive broker", "data acquisition", "backfill",
        "bars download", "data pipeline", "order routing", "paper trading",
        "execution", "headless gateway", "trading orchestr", "gateway lifecycle",
        "market data", "ibapi", "signal consumption",
    ],
}


def _classify_repo(text: str) -> Optional[str]:
    """Guess the most appropriate repo for a given prompt text."""
    text_lower = text.lower()
    scores: dict[str, int] = {repo: 0 for repo in _ROUTING_SIGNALS}
    for repo, keywords in _ROUTING_SIGNALS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[repo] += 1
    best_repo = max(scores, key=lambda r: scores[r])
    return best_repo if scores[best_repo] > 0 else None


def _validate_repo_boundary(
    text: str, repo: str, role: Optional[RepoRole]
) -> List[str]:
    """Return a list of boundary violation warnings for the given (text, repo) pair."""
    if role is None:
        return []
    violations: List[str] = []
    text_lower = text.lower()
    for forbidden in role.must_not_do:
        # Simple case-insensitive substring match for each word in the phrase
        # (e.g. "experiment tracking" matches "experiment tracking sweep")
        forbidden_lower = forbidden.lower()
        # Split multi-word phrases and check if all significant words appear nearby
        words = [w for w in forbidden_lower.split() if len(w) > 3]
        if words and all(w in text_lower for w in words):
            violations.append(
                f'Prompt touches "{forbidden}" which {repo} must NOT own — '
                f"consider routing to a different repo"
            )
    return violations


# ---------------------------------------------------------------------------
# Overlap check helpers
# ---------------------------------------------------------------------------


def _prompt_overlaps(
    prompt_text: str,
    report: LedgerReport,
) -> List[str]:
    """Return caution messages for any active tasks that overlap the prompt content."""
    prompt_areas = _text_areas(prompt_text)
    if not prompt_areas:
        return []

    cautions: List[str] = []
    for task in report.in_progress_tasks:
        from automation.repo_task_ledger import _task_areas

        task_areas = _task_areas(task)
        shared = prompt_areas & task_areas
        if shared:
            cautions.append(
                f"[{task.repo}] task {task.task_id} ({task.title[:50]}) is already "
                f"in-progress and touches: {', '.join(sorted(shared))}"
            )
    return cautions


# ---------------------------------------------------------------------------
# CoordinationGuard
# ---------------------------------------------------------------------------


class CoordinationGuard:
    """
    Evaluates a candidate prompt+repo pair against North Star and active tasks.

    Parameters
    ----------
    north_star:
        Pre-loaded NorthStarContext. If None, loads via get_north_star().
    ledger_report:
        Pre-loaded LedgerReport. If None, loads via get_ledger_report().
    alignment_block_threshold:
        Prompt alignment scores below this level cause a BLOCK for P0/P1 tasks.
        Default 0.0 means we never block purely on alignment (only warn).
    overlap_block_on_in_progress:
        If True, block when an in-progress task shares areas with the prompt.
        Default False (warn only).
    """

    def __init__(
        self,
        *,
        north_star: Optional[NorthStarContext] = None,
        ledger_report: Optional[LedgerReport] = None,
        alignment_block_threshold: float = 0.0,
        overlap_block_on_in_progress: bool = False,
    ) -> None:
        self._ns = north_star
        self._report = ledger_report
        self._align_block_threshold = alignment_block_threshold
        self._overlap_block = overlap_block_on_in_progress

    def _get_ns(self) -> NorthStarContext:
        if self._ns is None:
            self._ns = get_north_star()
        return self._ns

    def _get_report(self) -> LedgerReport:
        if self._report is None:
            self._report = get_ledger_report()
        return self._report

    # ---------------------------------------------------------------------------
    # Public evaluate
    # ---------------------------------------------------------------------------

    def evaluate(
        self,
        prompt_text: str,
        target_repo: Optional[str] = None,
    ) -> CoordinationDecision:
        """
        Evaluate a candidate prompt before dispatch.

        Parameters
        ----------
        prompt_text:
            The full prompt text about to be sent to an agent panel.
        target_repo:
            The repo this prompt is intended for (e.g. "TF", "Trading", "contracts").
            If None, the guard will attempt to infer it.
        """
        ns = self._get_ns()
        report = self._get_report()

        cautions: List[str] = []
        inferred_repo: Optional[str] = _classify_repo(prompt_text)

        # ------------------------------------------------------------------
        # 1. Routing: validate or infer target repo
        # ------------------------------------------------------------------
        decided_repo = target_repo or inferred_repo

        if target_repo and inferred_repo and target_repo != inferred_repo:
            cautions.append(
                f"Prompt signals belong to {inferred_repo} but you're targeting {target_repo}. "
                f"Double-check ownership."
            )

        if decided_repo and decided_repo not in REPO_DEPENDENCY_ORDER:
            # Unknown repo — warn but continue
            cautions.append(
                f"Unknown repo '{decided_repo}'. Known repos: {', '.join(REPO_DEPENDENCY_ORDER)}"
            )

        # ------------------------------------------------------------------
        # 2. Boundary check: does the prompt cross repo ownership lines?
        # ------------------------------------------------------------------
        if decided_repo:
            role = ns.role_for_repo(decided_repo)
            boundary_violations = _validate_repo_boundary(prompt_text, decided_repo, role)
            if boundary_violations:
                # Routing violation: recommend the correct repo via signal
                suggested = _classify_repo(prompt_text)
                if suggested and suggested != decided_repo:
                    return CoordinationDecision(
                        outcome=DecisionOutcome.REDIRECT,
                        target_repo=decided_repo,
                        redirect_to_repo=suggested,
                        block_reason=(
                            f"Prompt boundary violation in {decided_repo}: "
                            + "; ".join(boundary_violations[:2])
                        ),
                        cautions=cautions,
                        context_prefix=ns.prompt_header(),
                        alignment_score=0.0,
                    )
                else:
                    cautions.extend(boundary_violations)

        # ------------------------------------------------------------------
        # 3. Overlap check: is this work already in-flight?
        # ------------------------------------------------------------------
        overlap_cautions = _prompt_overlaps(prompt_text, report)
        if overlap_cautions:
            if self._overlap_block and report.in_progress_tasks:
                return CoordinationDecision(
                    outcome=DecisionOutcome.BLOCK,
                    target_repo=decided_repo,
                    block_reason=(
                        "Work already in-progress overlaps this prompt: "
                        + "; ".join(overlap_cautions[:3])
                    ),
                    cautions=cautions,
                    context_prefix=ns.prompt_header(),
                    alignment_score=0.0,
                )
            cautions.extend(
                [f"OVERLAP RISK: {c}" for c in overlap_cautions]
            )

        # ------------------------------------------------------------------
        # 4. Drift/alignment check
        # ------------------------------------------------------------------
        # Score the prompt against the North Star goal
        from automation.north_star import ActiveTask as _AT

        synthetic_task = _AT(
            task_id="_candidate_",
            title=prompt_text[:80],
            description=prompt_text[:400],
            status="planned",
            priority="P2",
            repo=decided_repo or "unknown",
        )
        alignment = _north_star_score(synthetic_task, ns)

        if alignment < self._align_block_threshold:
            return CoordinationDecision(
                outcome=DecisionOutcome.BLOCK,
                target_repo=decided_repo,
                block_reason=(
                    f"Prompt alignment score {alignment:.2f} is below threshold "
                    f"{self._align_block_threshold:.2f}. Prompt may be off-goal."
                ),
                cautions=cautions,
                context_prefix=ns.prompt_header(),
                alignment_score=alignment,
            )

        if alignment < 0.08 and not cautions:
            cautions.append(
                f"Low North Star alignment ({alignment:.2f}). "
                f"Confirm this advances: \"{ns.primary_goal[:80]}\""
            )

        # ------------------------------------------------------------------
        # 5. Build context prefix
        # ------------------------------------------------------------------
        context_prefix = _build_context_prefix(ns, report, decided_repo)

        # ------------------------------------------------------------------
        # Final outcome
        # ------------------------------------------------------------------
        outcome = (
            DecisionOutcome.PROCEED_WITH_CONTEXT
            if cautions
            else DecisionOutcome.PROCEED
        )

        return CoordinationDecision(
            outcome=outcome,
            target_repo=decided_repo,
            cautions=cautions,
            context_prefix=context_prefix,
            alignment_score=alignment,
        )

    def refresh(self) -> None:
        """Force-reload North Star and ledger caches."""
        from automation.north_star import get_north_star
        from automation.repo_task_ledger import get_ledger_report

        self._ns = get_north_star(force_refresh=True)
        self._report = get_ledger_report(force_refresh=True)


# ---------------------------------------------------------------------------
# Context prefix builder
# ---------------------------------------------------------------------------


def _build_context_prefix(
    ns: NorthStarContext,
    report: LedgerReport,
    target_repo: Optional[str],
) -> str:
    """Build the full context block to prepend to every dispatched prompt."""
    lines: List[str] = []

    # --- North Star header ---
    lines.append(ns.prompt_header())

    # --- In-flight work for THIS repo ---
    if target_repo:
        repo_tasks = report.active_tasks  # already filtered to active
        repo_in_progress = [t for t in repo_tasks if t.repo == target_repo and t.is_in_progress]
        if repo_in_progress:
            lines.append("")
            lines.append(f"### Work currently in-progress in {target_repo} (DO NOT duplicate):")
            for t in repo_in_progress:
                lines.append(f"  - {t.task_id}: {t.title}")

    # --- Coordination issues (overlap + drift) ---
    issues: List[str] = []
    for w in report.overlap_warnings:
        issues.append(f"⚠ OVERLAP: {w}")
    for w in report.drift_warnings:
        issues.append(f"⚠ DRIFT: {w}")
    if issues:
        lines.append("")
        lines.append("### Active coordination issues:")
        lines.extend([f"  {i}" for i in issues[:5]])  # cap to avoid bloating prompts
        if len(issues) > 5:
            lines.append(f"  … and {len(issues) - 5} more. Run `coord status` for full report.")

    # --- Repo ownership reminder ---
    if target_repo:
        role = ns.role_for_repo(target_repo)
        if role:
            lines.append("")
            lines.append(f"### {target_repo} owns:")
            for own in role.owns[:3]:
                lines.append(f"  ✓ {own}")
            lines.append(f"### {target_repo} must NOT do:")
            for forbidden in role.must_not_do[:3]:
                lines.append(f"  ✗ {forbidden}")

    lines.append("")
    lines.append(
        "---\n"
        "Check the above context before starting any work. "
        "If this task is already tracked in agent_assignments.json or conflicts with "
        "in-flight work, pause and discuss with the human operator before proceeding."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_guard: Optional[CoordinationGuard] = None


def get_coordination_guard() -> CoordinationGuard:
    """Return a module-level singleton CoordinationGuard."""
    global _guard
    if _guard is None:
        _guard = CoordinationGuard()
    return _guard
