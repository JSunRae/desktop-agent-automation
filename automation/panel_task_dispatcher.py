from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

from automation import prompt_resolver
from automation.config import FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK
from automation.prompt_scoring import PromptScorer

if TYPE_CHECKING:  # pragma: no cover - imported for type hints only
    from automation.panel_tracker import PanelTracker, PanelState

DEFAULT_REPO_PROMPT_KEY = "__default__"
ASSIGNED_PROMPT_PREVIEW_CHARS = 200
ASSIGNED_PROMPT_ID_LEN = 12


@dataclass
class TaskFeedEntry:
    """Single unit of work pulled from the prompt feed."""

    repo_key: str
    repo_name: Optional[str]
    prompt_index: int
    prompt_text: str
    prompt_preview: str
    prompt_id: str
    task_id: str
    model_label: str
    source_path: Path
    batch_id: Optional[str]
    quality_score: float = 0.0
    quality_notes: List[str] = field(default_factory=list)


@dataclass
class TaskFeedCache:
    """Cache entry describing the prompts available for a repo."""

    entries: List[TaskFeedEntry]
    fingerprint: str
    batch_id: Optional[str]
    source_path: Path
    next_index: int = 0


class TaskPanelDispatcher:
    """Assigns prompts from the cross-repo feed to finished panels."""

    def __init__(
        self,
        prompt_path: Optional[Path] = None,
        *,
        allow_default_fallback: Optional[bool] = None,
    ) -> None:
        if prompt_path is None:
            prompt_path = prompt_resolver.FINISHED_PANEL_PROMPT_PATH
        self.default_prompt_path = prompt_path
        self.feed_root = prompt_path.parent
        self.allow_default_fallback = (
            FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK
            if allow_default_fallback is None
            else allow_default_fallback
        )
        self._feed_cache: Dict[str, TaskFeedCache] = {}
        self._active_assignments: Dict[str, str] = {}
        self._idle_panel_keys: List[str] = []
        self._missing_repos: set[str] = set()
        self._prompt_scorer = PromptScorer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reset_cache(self) -> None:
        """Clear cached prompt batches (primarily used in tests)."""
        self._feed_cache.clear()

    def sync_active_assignments(self, tracker: "PanelTracker") -> None:
        """Rebuild the set of active task assignments from tracker state."""
        new_assignments: Dict[str, str] = {}
        for panel in tracker.panels.values():
            task_id = getattr(panel, "assigned_task_id", None)
            if not task_id:
                continue
            panel_key = tracker.build_panel_key(panel)
            new_assignments[task_id] = panel_key
        self._active_assignments = new_assignments

    def track_idle_panels(self, panel_keys: Sequence[str]) -> None:
        """Record which panels are currently idle for debugging/telemetry."""
        self._idle_panel_keys = list(panel_keys)

    def get_low_task_repos(self, repo_names: Optional[List[str]] = None, threshold: int = 2) -> List[str]:
        """Identify repositories that have fewer than 'threshold' tasks remaining.
        
        If repo_names is provided, it will ensure those repos are checked (loading them if necessary).
        Otherwise, it only checks repos already in the cache or known to be missing.
        """
        low_repos = []
        
        if repo_names:
            for name in repo_names:
                cache = self._get_feed_cache(name)
                if len(cache.entries) < threshold:
                    low_repos.append(name)
            return low_repos

        # Fallback to checking what we already know
        for repo_key, cache in self._feed_cache.items():
            if len(cache.entries) < threshold:
                low_repos.append(repo_key)

        for repo_key in self._missing_repos:
            if repo_key not in low_repos:
                low_repos.append(repo_key)

        return low_repos

    def reserve_task_for_panel(
        self,
        *,
        tracker: "PanelTracker",
        panel: "PanelState",
        panel_key: str,
        repo_name: Optional[str],
    ) -> Optional[TaskFeedEntry]:
        """Find the next available task for the given panel."""
        cache = self._get_feed_cache(repo_name)
        entries = cache.entries
        if not entries:
            return None

        prompt_count = len(entries)
        repo_key = get_repo_prompt_cache_key(repo_name)
        start_index = cache.next_index % prompt_count if prompt_count else 0

        for offset in range(prompt_count):
            idx = (start_index + offset) % prompt_count
            entry = entries[idx]
            active_owner = self._active_assignments.get(entry.task_id)
            if active_owner and active_owner != panel_key:
                continue

            self._active_assignments[entry.task_id] = panel_key
            tracker.advance_prompt_index(repo_name, steps=offset + 1)
            self._missing_repos.discard(repo_key)
            cache.next_index = (idx + 1) % prompt_count
            return entry

        if repo_key not in self._missing_repos:
            label = repo_name or "default"
            print(
                f"[TaskPanelDispatcher] No prompts remaining for repo '{label}'."
            )
            self._missing_repos.add(repo_key)
        return None

    def release_task(self, task_id: Optional[str], panel_key: str) -> None:
        """Release a reserved task so it can be reassigned."""
        if not task_id:
            return
        owner = self._active_assignments.get(task_id)
        if owner == panel_key:
            self._active_assignments.pop(task_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_feed_cache(self, repo_name: Optional[str]) -> TaskFeedCache:
        repo_key = get_repo_prompt_cache_key(repo_name)
        path = self._resolve_prompt_path_for_repo(repo_name)
        fingerprint = self._fingerprint_path(path)
        cached = self._feed_cache.get(repo_key)
        if cached and cached.fingerprint == fingerprint:
            return cached
        entries, batch_id = self._load_entries_from_path(path, repo_key, repo_name)
        cache = TaskFeedCache(
            entries=entries,
            fingerprint=fingerprint,
            batch_id=batch_id,
            source_path=path,
        )
        self._feed_cache[repo_key] = cache
        return cache

    def _resolve_prompt_path_for_repo(self, repo_name: Optional[str]) -> Path:
        """Resolve which prompt feed file to use for a repo.

        Resolution order:
        1) Exact matches in REPO_PROMPT_MAP
        2) <feed_root>/<repo_name>/latest.txt when it exists
        3) default prompt feed only if allow_default_fallback=True

        When allow_default_fallback=False, missing repo feeds return the expected
        repo-specific path (even if missing) so callers can log clearly.
        """
        # The dispatcher is always configured with a default prompt feed.
        # For the default repo (repo_name is None), always use that feed.
        if not repo_name:
            return self.default_prompt_path

        if repo_name:
            for configured_repo, prompt_path in prompt_resolver.REPO_PROMPT_MAP.items():
                if configured_repo.lower() == repo_name.lower():
                    return Path(prompt_path)

            repo_specific_path = self.feed_root / repo_name / prompt_resolver.PROMPT_FEED_FILENAME
            if repo_specific_path.exists():
                return repo_specific_path

            if self.allow_default_fallback:
                return self.default_prompt_path
            return repo_specific_path

        # (unreachable due to the early return above)
        return self.default_prompt_path

    def _fingerprint_path(self, path: Path) -> str:
        try:
            stat = path.stat()
            return f"{stat.st_mtime_ns}:{stat.st_size}"
        except FileNotFoundError:
            return "missing"

    def _load_entries_from_path(
        self,
        path: Path,
        repo_key: str,
        repo_name: Optional[str],
    ) -> Tuple[List[TaskFeedEntry], Optional[str]]:
        if not path.exists():
            if repo_key not in self._missing_repos:
                label = repo_name or "default"
                print(
                    f"[TaskPanelDispatcher] Prompt feed not found for repo '{label}' ({path})."
                )
                self._missing_repos.add(repo_key)
            return [], None

        text = path.read_text(encoding="utf-8", errors="ignore")
        batch_id = _extract_batch_id(text)
        prompts = _split_prompt_blocks(text)
        entries: List[TaskFeedEntry] = []
        for index, prompt in enumerate(prompts):
            prompt_id = compute_prompt_identifier(prompt)
            if not prompt_id:
                continue
            task_id = build_task_id(repo_name, prompt_id)
            entries.append(
                TaskFeedEntry(
                    repo_key=repo_key,
                    repo_name=repo_name,
                    prompt_index=index,
                    prompt_text=prompt,
                    prompt_preview=preview_prompt_text(prompt),
                    prompt_id=prompt_id,
                    task_id=task_id,
                    model_label=detect_model_label(prompt),
                    source_path=path,
                    batch_id=batch_id,
                )
            )
        return self._score_entries(entries), batch_id

    def _score_entries(self, entries: List[TaskFeedEntry]) -> List[TaskFeedEntry]:
        if not entries:
            return entries
        for entry in entries:
            score = self._prompt_scorer.score_prompt(entry.prompt_text, entry.prompt_id)
            entry.quality_score = score.total
            entry.quality_notes = score.notes
        entries.sort(key=lambda e: e.quality_score, reverse=True)
        return entries


# ============================================================================
# Module-level helpers shared with panel_tracker and tests
# ============================================================================

def build_task_id(repo_name: Optional[str], prompt_id: str) -> str:
    repo_label = (repo_name or "default").strip().lower().replace(" ", "-")
    return f"{repo_label}:{prompt_id}"


def get_repo_prompt_cache_key(repo_name: Optional[str]) -> str:
    return (repo_name or DEFAULT_REPO_PROMPT_KEY).lower()


def resolve_prompt_path_for_repo(repo_name: Optional[str]) -> Path:
    """Legacy resolver used by non-dispatcher helpers.

    NOTE: This resolver now respects FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK.
    """
    feed_root = prompt_resolver.FINISHED_PANEL_PROMPT_PATH.parent

    if repo_name:
        for configured_repo, prompt_path in prompt_resolver.REPO_PROMPT_MAP.items():
            if configured_repo.lower() == repo_name.lower():
                return Path(prompt_path)
        repo_specific_path = feed_root / repo_name / "latest.txt"
        if repo_specific_path.exists():
            return repo_specific_path
        if FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK:
            return prompt_resolver.FINISHED_PANEL_PROMPT_PATH
        return repo_specific_path

    if FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK:
        return prompt_resolver.FINISHED_PANEL_PROMPT_PATH
    return feed_root / DEFAULT_REPO_PROMPT_KEY / prompt_resolver.PROMPT_FEED_FILENAME


def load_prompt_blocks(path: Optional[Path] = None) -> List[str]:
    target_path = path or prompt_resolver.FINISHED_PANEL_PROMPT_PATH
    if not target_path.exists():
        return []
    try:
        raw = target_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return _split_prompt_blocks(raw)


def load_prompt_blocks_for_repo(repo_name: Optional[str]) -> List[str]:
    return load_prompt_blocks(resolve_prompt_path_for_repo(repo_name))


def detect_model_label(prompt_text: str) -> str:
    header = prompt_text.splitlines()[0] if prompt_text else ""
    header_lower = header.lower()
    if "codex-max" in header_lower or "codex max" in header_lower:
        return "GPT-5.1-Codex-Max (Preview)"
    if "codex mini" in header_lower or "codex-mini" in header_lower:
        return "GPT-5.1 Codex Mini"
    if "codex" in header_lower:
        return "GPT-5.1 Codex"
    if "grok" in header_lower:
        return "Grok"
    return ""


def compute_prompt_identifier(prompt_text: str) -> str:
    if not prompt_text:
        return ""
    digest = hashlib.sha256(prompt_text.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:ASSIGNED_PROMPT_ID_LEN]


def preview_prompt_text(prompt_text: str) -> str:
    text = prompt_text.strip().replace("\r", "")
    if len(text) <= ASSIGNED_PROMPT_PREVIEW_CHARS:
        return text
    return text[: ASSIGNED_PROMPT_PREVIEW_CHARS - 3] + "..."


def _extract_batch_id(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _split_prompt_blocks(text: str) -> List[str]:
    blocks: List[str] = []
    current: List[str] = []
    numbered_heading = re.compile(r"^\s*(?:\d+\.|prompt\s+\d+)\s*", re.IGNORECASE)
    for line in text.splitlines():
        stripped = line.strip()
        if numbered_heading.match(stripped):
            if current:
                blocks.append("\n".join(current).strip())
            current = [stripped]
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


_dispatcher_instance: Optional[TaskPanelDispatcher] = None


def get_task_panel_dispatcher() -> TaskPanelDispatcher:
    """Return the singleton dispatcher instance."""
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = TaskPanelDispatcher()
    return _dispatcher_instance


def reset_task_panel_dispatcher() -> None:
    """Reset the singleton dispatcher (used in tests)."""
    global _dispatcher_instance
    _dispatcher_instance = None
