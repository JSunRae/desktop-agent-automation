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

    default_cache_path = getattr(
        config, "CROSS_REPO_TODO_CACHE_PATH", Path("automation/cross_repo_todo_cache.json")
    )
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
