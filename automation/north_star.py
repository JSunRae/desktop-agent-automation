"""North Star: canonical goal and alignment context for the trading-system multi-repo workspace.

This module loads the authoritative guidance from the trading-system repos so that every
generated prompt is anchored to the single highest-priority goal and stays within the correct
repo boundaries.

Sources (in priority order):
  1. Trading/agent_assignments.json   – operative P0/P1 tasks (execution ledger)
  2. trading-system AGENTS.md         – routing matrix and cross-repo structure
  3. Repo AGENTS.md / copilot-instructions – per-repo role boundaries

The NorthStarContext produced here is injected into every prompt by the orchestrator so
agents always know:
  - What the top-level goal is right now
  - Which repo owns which kind of work
  - What is currently in-flight across all repos (to avoid overlap)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from automation.config import (
    NORTH_STAR_CACHE_TTL_SECONDS,
    TRADING_SYSTEM_ROOT,
    WSL_PATH_PROBE_TIMEOUT_SECONDS,
)
from automation.utils import probe_wsl_path

# ---------------------------------------------------------------------------
# Path constants (resolved via env vars so CI/tests can override them)
# ---------------------------------------------------------------------------

_WSL_BASE = TRADING_SYSTEM_ROOT
NORTH_STAR_CACHE_PATH = Path("state") / "north_star_cache.json"

TRADING_SYSTEM_ROOT: Path = _WSL_BASE
TRADING_REPO_ROOT: Path = _WSL_BASE / "Trading"
TF_REPO_ROOT: Path = _WSL_BASE / "TF"
CONTRACTS_REPO_ROOT: Path = _WSL_BASE / "contracts"

# Canonical file paths
WORKSPACE_AGENTS_MD: Path = _WSL_BASE / "AGENTS.md"
TRADING_ASSIGNMENTS: Path = TRADING_REPO_ROOT / "agent_assignments.json"

# Known additional per-workspace assignment ledgers (add more as repos get them)
REPO_ASSIGNMENT_LEDGERS: Dict[str, Path] = {
    "Trading": TRADING_REPO_ROOT / "agent_assignments.json",
    "TF": TF_REPO_ROOT / "agent_assignments.json",       # may not exist yet
    "contracts": CONTRACTS_REPO_ROOT / "agent_assignments.json",  # may not exist yet
}

# Canonical repo docs that define the role of each repo
REPO_ALIGNMENT_DOCS: Dict[str, List[Path]] = {
    "Trading": [
        TRADING_REPO_ROOT / "README.md",
        TRADING_REPO_ROOT / "AGENTS.md",
        TRADING_REPO_ROOT / ".github" / "copilot-instructions.md",
    ],
    "TF": [
        TF_REPO_ROOT / "README.md",
        TF_REPO_ROOT / "AGENTS.md",
        TF_REPO_ROOT / ".github" / "copilot-instructions.md",
    ],
    "contracts": [
        CONTRACTS_REPO_ROOT / "README.md",
        CONTRACTS_REPO_ROOT / ".github" / "copilot-instructions.md",
    ],
}

# Dependency/promotion order (upstream → downstream)
REPO_DEPENDENCY_ORDER: List[str] = ["contracts", "TF", "Trading"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ActiveTask:
    """A task that is currently in-flight in any of the repos."""

    task_id: str
    title: str
    description: str
    status: str          # planned / in_progress / blocked / review / completed / cancelled
    priority: str        # P0 / P1 / P2 / P3
    repo: str
    assignee_id: Optional[str] = None
    claimed_at: Optional[str] = None
    updated_at: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    note_preview: Optional[str] = None  # last note text for context

    @property
    def is_active(self) -> bool:
        return self.status in ("in_progress", "planned", "blocked", "review")

    @property
    def is_in_progress(self) -> bool:
        return self.status == "in_progress"


@dataclass
class RepoRole:
    """Defines what a repo owns and what it must not do."""

    name: str
    owns: List[str]          # e.g. ["ML training", "model export", "feature engineering"]
    must_not_do: List[str]   # e.g. ["order execution", "broker connectivity"]
    depends_on: List[str]    # upstream repos
    depended_on_by: List[str]  # downstream repos


@dataclass
class NorthStarContext:
    """
    The authoritative context injected into every generated prompt.

    Keeps agents oriented toward the top-level goal and prevents them from
    crossing repo boundaries or duplicating work already in-flight.
    """

    # The single most important goal right now
    primary_goal: str
    primary_task_id: Optional[str]

    # All currently active tasks (across all repos), newest first
    active_tasks: List[ActiveTask]

    # Canonical roles for each repo
    repo_roles: Dict[str, RepoRole]

    # Cross-repo dependency order
    dependency_order: List[str]

    # Plain-text routing summary (from workspace AGENTS.md)
    routing_summary: str

    # When this context was loaded
    loaded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ---------------------------------------------------------------------------
    # Convenience helpers
    # ---------------------------------------------------------------------------

    def tasks_for_repo(self, repo: str) -> List[ActiveTask]:
        return [t for t in self.active_tasks if t.repo == repo]

    def in_progress_tasks(self) -> List[ActiveTask]:
        return [t for t in self.active_tasks if t.is_in_progress]

    def p0_tasks(self) -> List[ActiveTask]:
        return [t for t in self.active_tasks if t.priority == "P0" and t.is_active]

    def role_for_repo(self, repo: str) -> Optional[RepoRole]:
        return self.repo_roles.get(repo)

    def prompt_header(self) -> str:
        """Return a concise block to prepend to every agent prompt."""
        lines: List[str] = []
        lines.append("## NORTH STAR — STAY ON GOAL")
        lines.append("")
        lines.append(f"**Primary goal:** {self.primary_goal}")
        lines.append("")
        if self.in_progress_tasks():
            lines.append("**Work currently in-flight (DO NOT duplicate):**")
            for t in self.in_progress_tasks():
                lines.append(f"  - [{t.repo}] {t.task_id}: {t.title}")
        lines.append("")
        lines.append("**Repo ownership:**")
        for repo in self.dependency_order:
            role = self.repo_roles.get(repo)
            if role:
                owns_str = "; ".join(role.owns[:3])
                lines.append(f"  - **{repo}**: {owns_str}")
        lines.append("")
        lines.append(
            "Confirm that your work targets the correct repo and does not overlap with any "
            "in-flight task listed above before proceeding."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _safe_read(path: Path, max_chars: int = 4000) -> Optional[str]:
    """Read a file, suppressing errors. Returns None if unreadable."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return raw[:max_chars] if len(raw) > max_chars else raw
    except Exception:
        return None


def _load_assignment_ledger(path: Path, repo: str) -> List[ActiveTask]:
    """Parse a repo's agent_assignments.json into ActiveTask objects."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    tasks_raw: List[Dict[str, Any]] = data.get("tasks", [])
    results: List[ActiveTask] = []

    for raw in tasks_raw:
        status = str(raw.get("status", "planned")).lower()
        if status in ("completed", "cancelled"):
            continue  # skip finished work

        assignee = raw.get("assignee") or raw.get("claimed_by") or {}
        assignee_id: Optional[str] = None
        if isinstance(assignee, dict):
            assignee_id = assignee.get("id")
        elif isinstance(assignee, str):
            assignee_id = assignee

        notes: List[Dict] = raw.get("notes", [])
        note_preview: Optional[str] = None
        if notes:
            last = notes[-1]
            note_preview = str(last.get("message", ""))[:200]

        results.append(
            ActiveTask(
                task_id=str(raw.get("id", "")),
                title=str(raw.get("title", "")),
                description=str(raw.get("description", ""))[:500],
                status=status,
                priority=str(raw.get("priority", "P2")),
                repo=repo,
                assignee_id=assignee_id,
                claimed_at=raw.get("claimed_at"),
                updated_at=raw.get("updated_at"),
                tags=raw.get("tags", []),
                acceptance_criteria=raw.get("acceptance_criteria", []),
                note_preview=note_preview,
            )
        )
    return results


def _parse_routing_summary(agents_md: Optional[str]) -> str:
    """Extract the routing matrix from the workspace AGENTS.md."""
    if not agents_md:
        return (
            "Trading: execution/data acquisition | "
            "TF: ML model training/export | "
            "contracts: schemas/rules/fixtures"
        )

    # Find the Fast Routing Matrix table or Mode Selection section
    section_match = re.search(
        r"(## Fast Routing Matrix.*?)(?=\n## |\Z)",
        agents_md,
        re.DOTALL,
    )
    if section_match:
        raw = section_match.group(1)
        # Trim to keep it concise
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        return "\n".join(lines[:20])

    # Fallback: grab first 600 chars of the file
    return agents_md[:600]


def _build_repo_roles() -> Dict[str, RepoRole]:
    """Return the canonical role definitions for each repo."""
    return {
        "contracts": RepoRole(
            name="contracts",
            owns=[
                "JSON Schemas (manifest, bars, L2, gap-opener)",
                "JSON-Logic promotion rules",
                "canonical fixtures and checksums",
                "schema versioning and governance",
            ],
            must_not_do=[
                "model code", "trading/execution code", "notebooks",
                "general-purpose scripts outside governance tooling",
            ],
            depends_on=[],
            depended_on_by=["TF", "Trading"],
        ),
        "TF": RepoRole(
            name="TF",
            owns=[
                "ML model training and evaluation",
                "feature and label engineering",
                "experiment tracking (W&B)",
                "model export and manifest generation",
                "data preparation from Trading outputs",
            ],
            must_not_do=[
                "order execution", "position sizing", "broker connectivity",
                "IB gateway lifecycle", "live trading orchestration",
                "modifying contracts/ schemas directly",
            ],
            depends_on=["contracts"],
            depended_on_by=["Trading"],
        ),
        "Trading": RepoRole(
            name="Trading",
            owns=[
                "data acquisition and orchestration",
                "IB gateway lifecycle (headless, paper, live)",
                "market data pipelines (IBKR, DataBento)",
                "signal consumption and order routing",
                "manifest consumption under TRADING_SYSTEM_DATA",
            ],
            must_not_do=[
                "ML model training", "feature engineering", "experiment tracking",
                "signal generation (that is TF)",
                "modifying contracts/ schemas directly",
            ],
            depends_on=["contracts", "TF"],
            depended_on_by=[],
        ),
    }


def _derive_primary_goal(tasks: List[ActiveTask]) -> tuple[str, Optional[str]]:
    """Return (goal_text, task_id) for the highest-priority active task."""
    p0 = [t for t in tasks if t.priority == "P0" and t.is_active]
    p1 = [t for t in tasks if t.priority == "P1" and t.is_active]
    candidates = (p0 or p1 or [t for t in tasks if t.is_active])
    if not candidates:
        return (
            "Advance the trading-system toward repeatable, paper-trading-ready automated operation.",
            None,
        )
    # Sort: in_progress first, then by priority
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    status_rank = {"in_progress": 0, "review": 1, "planned": 2, "blocked": 3}
    candidates.sort(
        key=lambda t: (priority_rank.get(t.priority, 9), status_rank.get(t.status, 9))
    )
    top = candidates[0]
    goal = top.description[:300] if top.description else top.title
    return goal, top.task_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_north_star(
    *,
    trading_system_root: Optional[Path] = None,
    ledger_overrides: Optional[Dict[str, Path]] = None,
) -> NorthStarContext:
    """
    Load the NorthStarContext from the trading-system repos.

    Parameters
    ----------
    trading_system_root:
        Override the default TRADING_SYSTEM_ROOT path.
    ledger_overrides:
        Map repo name → assignment ledger path. Used in tests.
    """
    root = trading_system_root or TRADING_SYSTEM_ROOT
    trading_root = root / "Trading"
    tf_root = root / "TF"
    contracts_root = root / "contracts"

    ledgers: Dict[str, Path] = {
        "Trading": trading_root / "agent_assignments.json",
        "TF": tf_root / "agent_assignments.json",
        "contracts": contracts_root / "agent_assignments.json",
    }
    if ledger_overrides:
        ledgers.update(ledger_overrides)

    # Load all active tasks from all repos
    all_tasks: List[ActiveTask] = []
    for repo_name, ledger_path in ledgers.items():
        all_tasks.extend(_load_assignment_ledger(ledger_path, repo_name))

    # Sort: in-progress P0 first
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    status_rank = {"in_progress": 0, "review": 1, "planned": 2, "blocked": 3}
    all_tasks.sort(
        key=lambda t: (priority_rank.get(t.priority, 9), status_rank.get(t.status, 9))
    )

    # Load workspace AGENTS.md for routing summary
    workspace_agents_md = _safe_read(root / "AGENTS.md", max_chars=6000)
    routing_summary = _parse_routing_summary(workspace_agents_md)

    # Build repo roles
    repo_roles = _build_repo_roles()

    # Derive primary goal from tasks
    primary_goal, primary_task_id = _derive_primary_goal(all_tasks)

    return NorthStarContext(
        primary_goal=primary_goal,
        primary_task_id=primary_task_id,
        active_tasks=all_tasks,
        repo_roles=repo_roles,
        dependency_order=REPO_DEPENDENCY_ORDER,
        routing_summary=routing_summary,
    )


# Singleton cache -----------------------------------------------------------
_cached_context: Optional[NorthStarContext] = None
_cache_loaded_at: Optional[datetime] = None
_CACHE_TTL_SECONDS = NORTH_STAR_CACHE_TTL_SECONDS


def _north_star_from_dict(payload: Dict[str, Any]) -> NorthStarContext:
    active_tasks = [ActiveTask(**task) for task in payload.get("active_tasks", [])]
    repo_roles = {
        name: RepoRole(**role)
        for name, role in payload.get("repo_roles", {}).items()
    }
    return NorthStarContext(
        primary_goal=payload.get("primary_goal", ""),
        primary_task_id=payload.get("primary_task_id"),
        active_tasks=active_tasks,
        repo_roles=repo_roles,
        dependency_order=payload.get("dependency_order", REPO_DEPENDENCY_ORDER),
        routing_summary=payload.get("routing_summary", ""),
        loaded_at=payload.get("loaded_at", datetime.now(timezone.utc).isoformat()),
    )


def _load_cached_north_star(cache_path: Optional[Path] = None) -> Optional[NorthStarContext]:
    resolved_cache_path = cache_path or NORTH_STAR_CACHE_PATH
    try:
        payload = json.loads(resolved_cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return _north_star_from_dict(payload)
    except Exception:
        return None


def _write_cached_north_star(
    context: NorthStarContext,
    cache_path: Optional[Path] = None,
) -> None:
    resolved_cache_path = cache_path or NORTH_STAR_CACHE_PATH
    resolved_cache_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_cache_path.write_text(json.dumps(asdict(context), indent=2), encoding="utf-8")


def get_north_star(*, force_refresh: bool = False) -> NorthStarContext:
    """Return a (possibly cached) NorthStarContext. Thread-safe at module import."""
    global _cached_context, _cache_loaded_at
    now = datetime.now(timezone.utc)
    stale = (
        _cached_context is None
        or _cache_loaded_at is None
        or (now - _cache_loaded_at).total_seconds() > _CACHE_TTL_SECONDS
    )
    if force_refresh or stale:
        if not probe_wsl_path(TRADING_SYSTEM_ROOT, WSL_PATH_PROBE_TIMEOUT_SECONDS):
            cached_context = _load_cached_north_star()
            if cached_context is not None:
                _cached_context = cached_context
                _cache_loaded_at = now
                return cached_context
        try:
            _cached_context = load_north_star()
            _write_cached_north_star(_cached_context)
        except Exception as exc:  # pragma: no cover
            # If loading fails, return a minimal fallback context
            cached_context = _load_cached_north_star()
            if cached_context is not None:
                _cached_context = cached_context
                _cache_loaded_at = now
                return cached_context
            if _cached_context is not None:
                return _cached_context  # use stale cache rather than crashing
            _cached_context = NorthStarContext(
                primary_goal=(
                    "Advance the trading-system toward repeatable, "
                    "paper-trading-ready automated operation. "
                    f"(North Star load failed: {exc})"
                ),
                primary_task_id=None,
                active_tasks=[],
                repo_roles=_build_repo_roles(),
                dependency_order=REPO_DEPENDENCY_ORDER,
                routing_summary=(
                    "Trading: execution/data | TF: ML models | contracts: schemas"
                ),
            )
        _cache_loaded_at = now
    assert _cached_context is not None
    return _cached_context
