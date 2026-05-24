from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class TodoItem:
    text: str
    title: str
    priority: Optional[str] = None  # e.g., P0/P1/P2/P3/high/medium/low
    is_blocked: bool = False
    blocked_by: List[str] = field(default_factory=list)
    section: Optional[str] = None


@dataclass(frozen=True)
class RepoTodoSnapshot:
    repo_name: str
    todo_paths: List[str]
    parsed_at: str
    items: List[TodoItem]

    @property
    def blocked_count(self) -> int:
        return sum(1 for item in self.items if item.is_blocked)


@dataclass(frozen=True)
class CrossRepoTodoSnapshot:
    version: int
    generated_at: str
    repos: List[RepoTodoSnapshot]


@dataclass(frozen=True)
class TaskRef:
    """Lightweight reference to a Todo item within a cross-repo snapshot.

    The `key` is stable only within the lifetime of an analysis result and
    has the form "{repo_name}:{index}" where index is the item's position
    in that repo's item list.
    """

    key: str
    repo_name: str
    index: int
    title: str
    priority: Optional[str]
    is_blocked: bool
    blocked_by: List[str]


@dataclass(frozen=True)
class CrossRepoDependencyAnalysis:
    """Result of building a dependency graph across all discovered Todo items.

    Consumers can use the *_keys collections for stable identifiers and
    map back to `TaskRef` instances via the `tasks` mapping.
    """

    tasks: Mapping[str, TaskRef]
    dependencies: Mapping[str, List[str]]  # task_key -> prerequisite task_keys
    dependents: Mapping[str, List[str]]  # task_key -> tasks that depend on this key
    ordered_keys: List[str]  # topological order (best-effort) across all repos
    blocked_keys: List[str]
    unblocked_keys: List[str]
    cycles: List[List[str]]  # each cycle is a list of task_keys
    critical_path_keys: List[str]

    def iter_ordered(self) -> List[TaskRef]:
        return [self.tasks[k] for k in self.ordered_keys if k in self.tasks]

    def iter_critical_path(self) -> List[TaskRef]:
        return [self.tasks[k] for k in self.critical_path_keys if k in self.tasks]

    def tasks_for_repo(self, repo_name: str) -> List[TaskRef]:
        repo_lower = repo_name.lower()
        return [t for t in self.tasks.values() if t.repo_name.lower() == repo_lower]


_PRIORITY_RE = re.compile(
    r"(?i)(?:\[\s*)?(?:prio|priority|p)\s*[:\-]?\s*(p?[0-3]|high|medium|med|low)(?:\s*\])?"
)
_PN_RE = re.compile(r"(?i)\bP([0-3])\b")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_CHECKBOX_PREFIX_RE = re.compile(r"^\s*\[[ xX]\]\s*")


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_priority(raw: str) -> str:
    raw_norm = raw.strip().lower()
    if raw_norm in {"med"}:
        return "medium"
    if raw_norm.startswith("p") and len(raw_norm) == 2 and raw_norm[1].isdigit():
        return raw_norm.upper()
    if raw_norm.isdigit() and raw_norm in {"0", "1", "2", "3"}:
        return f"P{raw_norm}"
    return raw_norm


def _priority_rank(priority: Optional[str]) -> int:
    """Return a numeric rank for textual priorities.

    Lower numbers represent higher priority.
    """

    if not priority:
        return 3
    p = priority.strip().lower()
    if p in {"p0", "0", "high"}:
        return 0
    if p in {"p1", "1", "medium", "med"}:
        return 1
    if p in {"p2", "2", "low"}:
        return 2
    if p in {"p3", "3"}:
        return 3
    return 3


def parse_todo_markdown(content: str, *, repo_name: str, todo_path: Optional[str] = None) -> RepoTodoSnapshot:
    """Parse a Todo.md into structured items with priority + blockers.

    The parser is intentionally permissive: it extracts bullet/numbered lines and looks for common
    priority patterns (P0/P1/..., priority: high/medium/low) and blocker phrases.
    """
    section: Optional[str] = None
    items: List[TodoItem] = []

    for line in (content or "").splitlines():
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            section = heading_match.group(1).strip()
            continue

        bullet_match = _BULLET_RE.match(line)
        if not bullet_match:
            continue

        text = bullet_match.group(1).strip()
        if not text:
            continue

        # Remove checkbox prefix if present: "[ ] foo"
        text_no_checkbox = _CHECKBOX_PREFIX_RE.sub("", text).strip()

        # Priority extraction
        priority: Optional[str] = None
        prio_match = _PRIORITY_RE.search(text_no_checkbox)
        if prio_match:
            priority = _normalize_priority(prio_match.group(1))
        else:
            pn_match = _PN_RE.search(text_no_checkbox)
            if pn_match:
                priority = f"P{pn_match.group(1)}"

        # Blocker extraction
        lowered = text_no_checkbox.lower()
        is_blocked = "blocked" in lowered or (section or "").lower().startswith("block")
        blocked_by: List[str] = []
        by_idx = lowered.find("blocked by")
        if by_idx >= 0:
            tail = text_no_checkbox[by_idx + len("blocked by") :].strip(" :.-\t")
            if tail:
                blocked_by = [chunk.strip() for chunk in re.split(r"[,;]", tail) if chunk.strip()]

        # Title cleanup: strip obvious priority tokens and "blocked" marker prefixes
        title = text_no_checkbox
        title = re.sub(r"(?i)^\[\s*P\d\s*\]\s*", "", title).strip()
        title = re.sub(r"(?i)^P\d\s*[:\-]\s*", "", title).strip()
        title = re.sub(r"(?i)\bpriority\s*[:\-]\s*(?:p?[0-3]|high|medium|med|low)\b", "", title).strip()
        title = re.sub(r"(?i)^blocked\s*[:\-]\s*", "", title).strip()

        items.append(
            TodoItem(
                text=text_no_checkbox,
                title=title,
                priority=priority,
                is_blocked=is_blocked,
                blocked_by=blocked_by,
                section=section,
            )
        )

    todo_paths = [todo_path] if todo_path else []
    return RepoTodoSnapshot(repo_name=repo_name, todo_paths=todo_paths, parsed_at=_now_iso_utc(), items=items)


def _looks_like_repo_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / ".git").exists():
        return True
    if (path / "pyproject.toml").is_file() or (path / "requirements.txt").is_file():
        return True
    if (path / "docs").is_dir():
        return True
    return False


def _todo_candidates_for_repo_root(repo_root: Path) -> List[Path]:
    candidates: List[Path] = []

    for direct in [repo_root / "Todo.md", repo_root / "todo.md"]:
        if direct.is_file():
            candidates.append(direct)

    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        for doc_candidate in [docs_dir / "Todo.md", docs_dir / "todo.md", docs_dir / "TODO.md"]:
            if doc_candidate.is_file():
                candidates.append(doc_candidate)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: List[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def discover_repo_todos(
    *,
    workspace_root: Path,
    search_roots: Sequence[Path],
    repo_overrides: Mapping[str, Path],
) -> List[Tuple[str, Path]]:
    """Return (repo_name, todo_path) pairs discovered from overrides + sibling roots."""
    results: List[Tuple[str, Path]] = []
    checked: set[str] = set()

    def add(repo_name: str, todo_path: Path) -> None:
        key = f"{repo_name}:{todo_path}"
        if key in checked:
            return
        checked.add(key)
        results.append((repo_name, todo_path))

    # Overrides: explicit repo roots
    for name, repo_root in repo_overrides.items():
        for todo_path in _todo_candidates_for_repo_root(repo_root):
            add(name, todo_path)

    effective_search_roots = list(search_roots)
    if not effective_search_roots:
        effective_search_roots = [workspace_root.parent]

    for root in effective_search_roots:
        # root may be a repo dir or a container of repos
        if _looks_like_repo_dir(root):
            for todo_path in _todo_candidates_for_repo_root(root):
                add(root.name, todo_path)

        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if child.name.startswith("."):
                    continue
                if not _looks_like_repo_dir(child):
                    continue
                for todo_path in _todo_candidates_for_repo_root(child):
                    add(child.name, todo_path)
        except OSError:
            continue

    return results


class CrossRepoTodoIngestionService:
    """Discovers and parses sibling-repo Todo.md files into a refreshable on-disk cache."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        cache_path: Path,
        refresh_interval_seconds: int,
        search_roots: Sequence[Path],
        repo_overrides: Mapping[str, Path],
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.cache_path = cache_path
        self.refresh_interval_seconds = max(0, int(refresh_interval_seconds))
        self.search_roots = list(search_roots)
        self.repo_overrides = dict(repo_overrides)
        self._log = logger or (lambda msg: None)

        self._snapshot: Optional[CrossRepoTodoSnapshot] = None
        self._last_refresh_epoch: float = 0.0
        self._load_cache_if_present()

    def _load_cache_if_present(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._snapshot = _snapshot_from_dict(raw)
            self._last_refresh_epoch = time.time()
        except Exception:
            # Cache is best-effort; ignore corrupt files.
            self._snapshot = None
            self._last_refresh_epoch = 0.0

    def needs_refresh(self) -> bool:
        if self._snapshot is None:
            return True
        if self.refresh_interval_seconds <= 0:
            return False
        return (time.time() - self._last_refresh_epoch) >= self.refresh_interval_seconds

    def refresh(self) -> CrossRepoTodoSnapshot:
        discovered = discover_repo_todos(
            workspace_root=self.workspace_root,
            search_roots=self.search_roots,
            repo_overrides=self.repo_overrides,
        )
        repos: Dict[str, List[Path]] = {}
        for repo_name, todo_path in discovered:
            repos.setdefault(repo_name, []).append(todo_path)

        parsed_repos: List[RepoTodoSnapshot] = []
        for repo_name, todo_paths in sorted(repos.items(), key=lambda kv: kv[0].lower()):
            all_items: List[TodoItem] = []
            serialized_paths: List[str] = []
            for todo_path in todo_paths:
                serialized_paths.append(str(todo_path))
                try:
                    content = todo_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                repo_snapshot = parse_todo_markdown(content, repo_name=repo_name, todo_path=str(todo_path))
                all_items.extend(repo_snapshot.items)

            parsed_repos.append(
                RepoTodoSnapshot(
                    repo_name=repo_name,
                    todo_paths=serialized_paths,
                    parsed_at=_now_iso_utc(),
                    items=all_items,
                )
            )

        snapshot = CrossRepoTodoSnapshot(version=1, generated_at=_now_iso_utc(), repos=parsed_repos)
        self._snapshot = snapshot
        self._last_refresh_epoch = time.time()

        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(asdict(snapshot), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

        self._log(
            f"Cross-repo Todo cache refreshed: repos={len(snapshot.repos)} "
            f"items={sum(len(r.items) for r in snapshot.repos)}"
        )
        return snapshot

    def get_snapshot(self, *, force_refresh: bool = False) -> CrossRepoTodoSnapshot:
        if force_refresh or self.needs_refresh():
            return self.refresh()
        assert self._snapshot is not None
        return self._snapshot

    def render_summary_markdown(self, *, max_items_per_repo: int = 20) -> str:
        snapshot = self.get_snapshot()
        lines: List[str] = []
        lines.append("# Cross-Repo Todo Snapshot")
        lines.append(f"Generated at (UTC): {snapshot.generated_at}")
        lines.append("")

        if not snapshot.repos:
            lines.append("No Todo.md files discovered.")
            return "\n".join(lines).strip() + "\n"

        for repo in snapshot.repos:
            blocked = repo.blocked_count
            lines.append(f"## {repo.repo_name} (items: {len(repo.items)}, blocked: {blocked})")
            for todo_path in repo.todo_paths:
                lines.append(f"- Source: {todo_path}")

            if not repo.items:
                lines.append("- (No parseable bullet items)")
                lines.append("")
                continue

            shown = 0
            for item in repo.items:
                if shown >= max_items_per_repo:
                    break
                prio = f"[{item.priority}] " if item.priority else ""
                blocked_marker = " (BLOCKED)" if item.is_blocked else ""
                lines.append(f"- {prio}{item.title}{blocked_marker}")
                shown += 1
            if len(repo.items) > shown:
                lines.append(f"- … {len(repo.items) - shown} more")
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def analyze_dependencies(self) -> CrossRepoDependencyAnalysis:
        """Build and cache a dependency graph across all known Todo items.

        This is a higher-level view than the plain snapshot, providing
        ordering, cycle detection, and an approximate critical path.
        """

        snapshot = self.get_snapshot()
        return analyze_cross_repo_dependencies(snapshot)


def _snapshot_from_dict(raw: dict) -> CrossRepoTodoSnapshot:
    repos: List[RepoTodoSnapshot] = []
    for repo_raw in raw.get("repos", []) or []:
        items: List[TodoItem] = []
        for item_raw in repo_raw.get("items", []) or []:
            items.append(
                TodoItem(
                    text=str(item_raw.get("text", "")),
                    title=str(item_raw.get("title", "")),
                    priority=item_raw.get("priority"),
                    is_blocked=bool(item_raw.get("is_blocked", False)),
                    blocked_by=list(item_raw.get("blocked_by", []) or []),
                    section=item_raw.get("section"),
                )
            )
        repos.append(
            RepoTodoSnapshot(
                repo_name=str(repo_raw.get("repo_name", "")),
                todo_paths=list(repo_raw.get("todo_paths", []) or []),
                parsed_at=str(repo_raw.get("parsed_at", "")),
                items=items,
            )
        )

    return CrossRepoTodoSnapshot(
        version=int(raw.get("version", 1)),
        generated_at=str(raw.get("generated_at", "")),
        repos=repos,
    )


def analyze_cross_repo_dependencies(snapshot: CrossRepoTodoSnapshot) -> CrossRepoDependencyAnalysis:
    """Analyze dependencies across all repos in a snapshot.

    Dependency edges are inferred from each item's `blocked_by` strings by
    attempting to match those strings against other items' titles/text. The
    resulting graph is best-effort and designed to support summarisation and
    critical-path style reporting rather than strict enforcement.
    """

    tasks: Dict[str, TaskRef] = {}
    dependencies: Dict[str, List[str]] = {}
    dependents: Dict[str, List[str]] = {}

    # Build basic task index keyed by "repo_name:index".
    indexed_items: List[Tuple[str, str, TodoItem]] = []
    for repo in snapshot.repos:
        repo_lower = repo.repo_name.lower()
        for index, item in enumerate(repo.items):
            key = f"{repo.repo_name}:{index}"
            tasks[key] = TaskRef(
                key=key,
                repo_name=repo.repo_name,
                index=index,
                title=item.title,
                priority=item.priority,
                is_blocked=item.is_blocked,
                blocked_by=list(item.blocked_by or []),
            )
            dependencies[key] = []
            dependents[key] = []
            indexed_items.append((key, repo_lower, item))

    def _resolve_blocker_ref(blocker_raw: str, current_repo_lower: str) -> Optional[str]:
        token = (blocker_raw or "").strip().lower()
        if not token:
            return None

        # Direct key match (advanced users may reference "repo:index").
        if token in tasks:
            return token

        # First, prefer matches within the same repo.
        for key, repo_lower, item in indexed_items:
            if repo_lower != current_repo_lower:
                continue
            text_l = (item.text or "").lower()
            title_l = (item.title or "").lower()
            if token in title_l or token in text_l:
                return key

        # Fallback: any repo containing this token.
        for key, _repo_lower, item in indexed_items:
            text_l = (item.text or "").lower()
            title_l = (item.title or "").lower()
            if token in title_l or token in text_l:
                return key
        return None

    # Infer dependency edges from blocked_by annotations.
    for repo in snapshot.repos:
        current_repo_lower = repo.repo_name.lower()
        for index, item in enumerate(repo.items):
            to_key = f"{repo.repo_name}:{index}"
            for blocker in item.blocked_by or []:
                dep_key = _resolve_blocker_ref(blocker, current_repo_lower)
                if not dep_key or dep_key == to_key:
                    continue
                if dep_key not in tasks:
                    continue
                if dep_key not in dependencies[to_key]:
                    dependencies[to_key].append(dep_key)
                if to_key not in dependents[dep_key]:
                    dependents[dep_key].append(to_key)

    # Topological ordering via Kahn's algorithm with a priority-aware queue.
    in_degree: Dict[str, int] = {k: len(set(v)) for k, v in dependencies.items()}
    distance: Dict[str, int] = {k: 0 for k in tasks}

    ready: List[str] = [k for k, deg in in_degree.items() if deg == 0]

    def _sort_ready() -> None:
        ready.sort(
            key=lambda k: (
                _priority_rank(tasks[k].priority),
                tasks[k].repo_name.lower(),
                tasks[k].title.lower(),
            )
        )

    _sort_ready()
    ordered_keys: List[str] = []
    visited: set[str] = set()

    while ready:
        current = ready.pop(0)
        ordered_keys.append(current)
        visited.add(current)
        for dependent_key in dependents.get(current, []) or []:
            if dependent_key not in in_degree:
                continue
            # Each incoming edge has been accounted for in the initial in_degree.
            in_degree[dependent_key] -= 1
            if in_degree[dependent_key] == 0:
                ready.append(dependent_key)
                _sort_ready()
            # Longest-path distance (for DAG nodes only).
            if distance.get(dependent_key, 0) < distance.get(current, 0) + 1:
                distance[dependent_key] = distance.get(current, 0) + 1

    # Any nodes not visited are part of at least one cycle.
    cycle_nodes = set(tasks.keys()) - visited

    # Detect concrete cycles using DFS restricted to nodes suspected of being cyclic.
    cycles: List[List[str]] = []
    temp_mark: set[str] = set()
    perm_mark: set[str] = set()
    stack: List[str] = []

    def _visit(node: str) -> None:
        if node in perm_mark:
            return
        if node in temp_mark:
            # Found a cycle; capture the path from first occurrence of node.
            try:
                idx = stack.index(node)
                cycle = stack[idx:] + [node]
            except ValueError:
                cycle = [node]
            if cycle:
                cycles.append(cycle)
            return
        temp_mark.add(node)
        stack.append(node)
        for dep_key in dependencies.get(node, []) or []:
            if dep_key in cycle_nodes:
                _visit(dep_key)
        stack.pop()
        temp_mark.remove(node)
        perm_mark.add(node)

    for node in cycle_nodes:
        if node not in perm_mark:
            _visit(node)

    # Classify blocked vs unblocked using both explicit flags and inferred deps.
    blocked_keys: List[str] = []
    unblocked_keys: List[str] = []
    for key, ref in tasks.items():
        has_deps = bool(dependencies.get(key))
        if ref.is_blocked or has_deps:
            blocked_keys.append(key)
        else:
            unblocked_keys.append(key)

    # Compute a best-effort critical path over the DAG portion of the graph.
    critical_path_keys: List[str] = []
    if ordered_keys:
        # Restrict candidate endpoints to nodes that participate in ordering.
        max_node: Optional[str] = None
        max_dist = -1
        for key in ordered_keys:
            d = distance.get(key, 0)
            if d >= max_dist:
                max_dist = d
                max_node = key

        if max_node is not None and max_dist > 0:
            path: List[str] = [max_node]
            current = max_node
            while True:
                preds = [
                    p
                    for p in dependencies.get(current, []) or []
                    if p in tasks and distance.get(p, 0) == distance.get(current, 0) - 1
                ]
                if not preds:
                    break
                preds.sort(
                    key=lambda k: (
                        _priority_rank(tasks[k].priority),
                        tasks[k].repo_name.lower(),
                        tasks[k].title.lower(),
                    )
                )
                current = preds[0]
                path.append(current)
            critical_path_keys = list(reversed(path))

    return CrossRepoDependencyAnalysis(
        tasks=tasks,
        dependencies={k: list(v) for k, v in dependencies.items()},
        dependents={k: list(v) for k, v in dependents.items()},
        ordered_keys=list(ordered_keys),
        blocked_keys=blocked_keys,
        unblocked_keys=unblocked_keys,
        cycles=cycles,
        critical_path_keys=critical_path_keys,
    )


_DEFAULT_SINGLETON: Optional[CrossRepoTodoIngestionService] = None


def get_cross_repo_todo_service(
    *,
    workspace_root: Optional[Path] = None,
    cache_path: Optional[Path] = None,
    refresh_interval_seconds: Optional[int] = None,
    search_roots: Optional[Sequence[Path]] = None,
    repo_overrides: Optional[Mapping[str, Path]] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> CrossRepoTodoIngestionService:
    """Return a process-wide singleton service.

    This keeps cache and refresh cadence consistent when multiple modules request cross-repo data.
    """
    global _DEFAULT_SINGLETON
    if _DEFAULT_SINGLETON is not None:
        return _DEFAULT_SINGLETON

    import automation.config as config

    default_cache_path = getattr(config, "CROSS_REPO_TODO_CACHE_PATH", Path("private/runtime/cross_repo_todo_cache.json"))
    default_refresh = int(getattr(config, "CROSS_REPO_TODO_REFRESH_INTERVAL_SECONDS", 300))
    default_search_roots = list(getattr(config, "CROSS_REPO_TODO_SEARCH_ROOTS", []))
    default_overrides = dict(getattr(config, "CROSS_REPO_TODO_REPO_OVERRIDES", {}))

    _DEFAULT_SINGLETON = CrossRepoTodoIngestionService(
        workspace_root=workspace_root or Path.cwd(),
        cache_path=cache_path or default_cache_path,
        refresh_interval_seconds=(
            int(refresh_interval_seconds)
            if refresh_interval_seconds is not None
            else default_refresh
        ),
        search_roots=list(search_roots) if search_roots is not None else default_search_roots,
        repo_overrides=dict(repo_overrides) if repo_overrides is not None else default_overrides,
        logger=logger,
    )
    return _DEFAULT_SINGLETON
