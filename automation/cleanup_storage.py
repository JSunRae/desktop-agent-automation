"""Clean up VS Code workspace storage and cache bloat.

Targets old session/cache artifacts by age threshold, with repo-scoped
filtering, dry-run defaults, and per-repo confirmation controls.

Usage (standalone):
    python -m automation.cleanup_storage                          # dry-run
    python -m automation.cleanup_storage --execute                # actually delete
    python -m automation.cleanup_storage --repo my-project --execute
    python -m automation.cleanup_storage --older-than 30 --json

Wired into the master CLI as ``cleanup-storage``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from automation.diagnose_storage import (
    APPROVED_STORAGE_ROOTS,
    VSCODE_STORAGE_ROOTS,
    _dir_size,
    _format_bytes,
    _init_approved_roots,
    _repo_name_from_path,
    _resolve_repo_from_state_db,
    _resolve_repo_from_workspace_json,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AGE_DAYS = 60
"""Default age threshold in days — only items older than this are candidates."""

# Cache category patterns (matched against subfolder names inside workspace dirs)
CACHE_CATEGORIES: dict[str, list[str]] = {
    "session": ["history", "backupWorkspaces", "workspaceState"],
    "cache": ["Cache", "CachedData", "CachedExtensions", "CachedExtensionVSIXs", "GPUCache"],
    "logs": ["logs", "exthost", "crashReportMetadata"],
    "extensions": ["CachedExtensions", "CachedExtensionVSIXs"],
}

# Paths that must NEVER be deleted even if they match filters
PROTECTED_PATTERNS: set[str] = {
    "User/settings.json",
    "User/keybindings.json",
    "User/snippets",
    "extensions",
    "argv.json",
}

_IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CleanupCandidate:
    """A single item (file or folder) eligible for cleanup."""
    path: str
    size_bytes: int
    file_count: int
    last_modified: Optional[str] = None
    repo_name: Optional[str] = None
    repo_path: Optional[str] = None
    workspace_hash: Optional[str] = None
    category: str = "unknown"
    reason: str = ""


@dataclass
class RepoSummary:
    """Per-repo cleanup summary."""
    repo_name: str
    repo_path: Optional[str] = None
    candidate_count: int = 0
    reclaimable_bytes: int = 0
    categories: Dict[str, int] = field(default_factory=dict)


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""
    dry_run: bool = True
    timestamp: str = ""
    candidates_total: int = 0
    candidates_deleted: int = 0
    candidates_skipped: int = 0
    candidates_errored: int = 0
    bytes_reclaimable: int = 0
    bytes_reclaimed: int = 0
    repos_scanned: int = 0
    repos_affected: int = 0
    repo_summaries: list[RepoSummary] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    items: list[CleanupCandidate] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------

def _is_safe_target(path: Path) -> bool:
    """Return True only if *path* is within an approved storage root."""
    _init_approved_roots()
    resolved = path.resolve()
    # Must be descendant of at least one approved root
    for root in APPROVED_STORAGE_ROOTS:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    # Also allow direct children of VSCODE_STORAGE_ROOTS even if root didn't
    # exist at init time (the root folder itself)
    for root in VSCODE_STORAGE_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _is_symlink_escape(path: Path) -> bool:
    """Detect if *path* or any ancestor is a symlink pointing outside approved roots."""
    try:
        real = path.resolve(strict=False)
        if real != path.resolve():
            return not _is_safe_target(real)
    except (OSError, ValueError):
        return True
    return False


def _is_protected(path: Path) -> bool:
    """Return True if *path* matches any protected pattern."""
    path_str = str(path).replace("\\", "/")
    for pattern in PROTECTED_PATTERNS:
        if pattern in path_str:
            return True
    return False


def _refuse_dangerous(path: Path) -> Optional[str]:
    """Return an error reason string if *path* should NOT be deleted, else None."""
    if not path.exists():
        return "path does not exist"
    resolved = path.resolve()
    if resolved == Path.home().resolve():
        return "refusing to delete home directory"
    if resolved == Path("/").resolve() or (
        _IS_WINDOWS and len(str(resolved)) <= 3  # e.g., "C:\\"
    ):
        return "refusing to delete filesystem root"
    if not _is_safe_target(path):
        return f"path is outside approved storage roots: {resolved}"
    if _is_symlink_escape(path):
        return f"symlink escape detected: {path} -> {resolved}"
    if _is_protected(path):
        return f"path matches a protected pattern: {path}"
    return None


# ---------------------------------------------------------------------------
# Scanning / filtering
# ---------------------------------------------------------------------------

def _matches_category(name: str, include: set[str] | None, exclude: set[str] | None) -> bool:
    """Check if a subfolder *name* matches include/exclude category filters."""
    name_lower = name.lower()
    if include:
        for cat_key in include:
            patterns = CACHE_CATEGORIES.get(cat_key, [cat_key])
            if any(p.lower() in name_lower for p in patterns):
                return True
        return False
    if exclude:
        for cat_key in exclude:
            patterns = CACHE_CATEGORIES.get(cat_key, [cat_key])
            if any(p.lower() in name_lower for p in patterns):
                return False
    return True


def _categorize(name: str) -> str:
    name_lower = name.lower()
    for cat, patterns in CACHE_CATEGORIES.items():
        if any(p.lower() in name_lower for p in patterns):
            return cat
    return "other"


def _matches_repo_filters(
    repo_name: Optional[str],
    repo_path: Optional[str],
    ws_hash: str,
    *,
    repo_names: set[str] | None = None,
    exclude_repos: set[str] | None = None,
    repo_regex: re.Pattern | None = None,
    hash_prefixes: set[str] | None = None,
) -> bool:
    """Return True if entry passes all repo-scoped filters."""
    effective_name = (repo_name or "").lower()
    effective_path = (repo_path or "").lower()

    # Hash prefix filter
    if hash_prefixes:
        if not any(ws_hash.lower().startswith(h.lower()) for h in hash_prefixes):
            return False

    # Repo-name substring filter
    if repo_names:
        if not any(rn.lower() in effective_name or rn.lower() in effective_path for rn in repo_names):
            return False

    # Exclude-repo filter
    if exclude_repos:
        if any(er.lower() in effective_name or er.lower() in effective_path for er in exclude_repos):
            return False

    # Regex filter
    if repo_regex:
        combined = f"{repo_name or ''} {repo_path or ''}"
        if not repo_regex.search(combined):
            return False

    return True


def collect_candidates(
    *,
    older_than_days: int = DEFAULT_AGE_DAYS,
    include_categories: set[str] | None = None,
    exclude_categories: set[str] | None = None,
    include_extensions: bool = False,
    repo_names: set[str] | None = None,
    exclude_repos: set[str] | None = None,
    repo_regex: re.Pattern | None = None,
    hash_prefixes: set[str] | None = None,
) -> list[CleanupCandidate]:
    """Scan VS Code storage and return cleanup candidates matching all filters."""
    _init_approved_roots()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=older_than_days)
    candidates: list[CleanupCandidate] = []

    for root in VSCODE_STORAGE_ROOTS:
        if not root.exists() or not root.is_dir():
            continue

        is_workspace_root = "workspacestorage" in root.name.lower()

        if is_workspace_root:
            try:
                children = sorted(root.iterdir())
            except (OSError, PermissionError):
                continue
            for ws_dir in children:
                if not ws_dir.is_dir():
                    continue
                repo_path = _resolve_repo_from_workspace_json(ws_dir) or _resolve_repo_from_state_db(ws_dir)
                repo_name = _repo_name_from_path(repo_path)

                # Apply repo filters
                if not _matches_repo_filters(
                    repo_name, repo_path, ws_dir.name,
                    repo_names=repo_names, exclude_repos=exclude_repos,
                    repo_regex=repo_regex, hash_prefixes=hash_prefixes,
                ):
                    continue

                sz, fc, newest = _dir_size(ws_dir)
                if newest and newest < cutoff:
                    candidates.append(CleanupCandidate(
                        path=str(ws_dir),
                        size_bytes=sz,
                        file_count=fc,
                        last_modified=newest.isoformat() if newest else None,
                        repo_name=repo_name,
                        repo_path=repo_path,
                        workspace_hash=ws_dir.name,
                        category="workspaceStorage",
                        reason=f"workspace last modified {newest.date()} (>{older_than_days}d ago)",
                    ))
        else:
            # Non-workspace roots: check subfolders individually
            root_name = root.name
            if not include_extensions and root_name.lower() in {"cachedextensions", "cachedextensionvsixs"}:
                continue
            if not _matches_category(root_name, include_categories, exclude_categories):
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    sz, fc, newest = _dir_size(child)
                    if newest and newest < cutoff:
                        cat = _categorize(child.name)
                        candidates.append(CleanupCandidate(
                            path=str(child),
                            size_bytes=sz,
                            file_count=fc,
                            last_modified=newest.isoformat() if newest else None,
                            category=cat,
                            reason=f"{root_name}/{child.name} last modified {newest.date()} (>{older_than_days}d ago)",
                        ))
            except (OSError, PermissionError):
                continue

    candidates.sort(key=lambda c: c.size_bytes, reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def _rmtree_safe(path: Path) -> Tuple[bool, Optional[str]]:
    """Safely remove a directory tree. Returns (success, error_msg)."""
    danger = _refuse_dangerous(path)
    if danger:
        return False, danger
    try:
        def _on_error(func: Any, fpath: str, exc_info: Any) -> None:
            # Try to fix read-only files on Windows
            try:
                os.chmod(fpath, stat.S_IWRITE)
                func(fpath)
            except Exception:
                pass

        shutil.rmtree(str(path), onerror=_on_error)
        return True, None
    except Exception as exc:
        return False, str(exc)


def execute_cleanup(
    candidates: list[CleanupCandidate],
    *,
    dry_run: bool = True,
    confirm_each: bool = False,
    confirm_fn: Callable[[str], bool] | None = None,
) -> CleanupResult:
    """Delete (or simulate deletion of) the given candidates.

    Parameters
    ----------
    candidates:
        Items to clean.
    dry_run:
        If True (default), nothing is deleted.
    confirm_each:
        If True, call *confirm_fn* before each deletion.
    confirm_fn:
        Callback ``(description) -> bool``.  Defaults to stdin prompt.
    """
    result = CleanupResult(
        dry_run=dry_run,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
        candidates_total=len(candidates),
        items=candidates,
    )

    # Build per-repo summaries
    repo_map: Dict[str, RepoSummary] = {}
    repos_seen: set[str] = set()
    for c in candidates:
        key = c.repo_name or c.workspace_hash or c.category
        repos_seen.add(key)
        if key not in repo_map:
            repo_map[key] = RepoSummary(repo_name=key, repo_path=c.repo_path)
        repo_map[key].candidate_count += 1
        repo_map[key].reclaimable_bytes += c.size_bytes
        cat = c.category
        repo_map[key].categories[cat] = repo_map[key].categories.get(cat, 0) + c.size_bytes

    result.repo_summaries = sorted(repo_map.values(), key=lambda r: r.reclaimable_bytes, reverse=True)
    result.repos_scanned = len(repos_seen)
    result.bytes_reclaimable = sum(c.size_bytes for c in candidates)

    if dry_run:
        result.candidates_skipped = len(candidates)
        return result

    # Default confirm function
    if confirm_fn is None:
        def _default_confirm(desc: str) -> bool:
            try:
                answer = input(f"  Delete {desc}? [y/N] ").strip().lower()
                return answer in ("y", "yes")
            except (KeyboardInterrupt, EOFError):
                return False
        confirm_fn = _default_confirm

    affected_repos: set[str] = set()
    for c in candidates:
        path = Path(c.path)
        danger = _refuse_dangerous(path)
        if danger:
            result.errors.append(f"REFUSED {c.path}: {danger}")
            result.candidates_errored += 1
            continue

        if confirm_each:
            desc = f"{c.repo_name or c.workspace_hash or c.category} ({_format_bytes(c.size_bytes)})"
            if not confirm_fn(desc):
                result.candidates_skipped += 1
                continue

        success, err = _rmtree_safe(path)
        if success:
            result.candidates_deleted += 1
            result.bytes_reclaimed += c.size_bytes
            affected_repos.add(c.repo_name or c.workspace_hash or c.category)
        else:
            result.errors.append(f"ERROR {c.path}: {err}")
            result.candidates_errored += 1

    result.repos_affected = len(affected_repos)
    return result


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_preview(candidates: list[CleanupCandidate]) -> None:
    """Print a table of candidates that would be affected."""
    if not candidates:
        print("\n  No cleanup candidates found matching the given filters.\n")
        return

    total = sum(c.size_bytes for c in candidates)
    print(f"\n{'='*72}")
    print(f"  Storage Cleanup Preview  —  {len(candidates)} candidates, "
          f"{_format_bytes(total)} reclaimable")
    print(f"{'='*72}\n")

    # Per-repo summary first
    repo_totals: Dict[str, int] = {}
    for c in candidates:
        key = c.repo_name or c.workspace_hash or c.category
        repo_totals[key] = repo_totals.get(key, 0) + c.size_bytes

    print("  Impacted repos/categories:")
    for name, sz in sorted(repo_totals.items(), key=lambda x: x[1], reverse=True):
        print(f"    {name:<40} {_format_bytes(sz):>12}")

    print(f"\n  {'Category':<15} {'Size':>12} {'Files':>8} {'Repo/Folder':<30} {'Reason'}")
    print("  " + "-" * 90)

    for c in candidates:
        label = c.repo_name or c.workspace_hash or c.category
        print(f"  {c.category:<15} {_format_bytes(c.size_bytes):>12} {c.file_count:>8} "
              f"{label:<30} {c.reason}")

    print()


def print_result(result: CleanupResult, *, as_json: bool = False) -> None:
    """Print cleanup result summary."""
    if as_json:
        print(json.dumps(asdict(result), indent=2, default=str))
        return

    mode = "DRY-RUN" if result.dry_run else "EXECUTE"
    print(f"\n{'='*72}")
    print(f"  Storage Cleanup Result  [{mode}]  —  {result.timestamp}")
    print(f"{'='*72}")
    print(f"  Candidates total:    {result.candidates_total}")
    if result.dry_run:
        print(f"  Would delete:        {result.candidates_total} items")
        print(f"  Would reclaim:       {_format_bytes(result.bytes_reclaimable)}")
    else:
        print(f"  Deleted:             {result.candidates_deleted}")
        print(f"  Skipped:             {result.candidates_skipped}")
        print(f"  Errors:              {result.candidates_errored}")
        print(f"  Bytes reclaimed:     {_format_bytes(result.bytes_reclaimed)}")
    print(f"  Repos scanned:       {result.repos_scanned}")
    print(f"  Repos affected:      {result.repos_affected if not result.dry_run else result.repos_scanned}")
    print(f"{'='*72}")

    if result.repo_summaries:
        print("\n  Per-repo breakdown:")
        for rs in result.repo_summaries[:20]:
            label = "would reclaim" if result.dry_run else "reclaimable"
            print(f"    {rs.repo_name:<40} {_format_bytes(rs.reclaimable_bytes):>12}  "
                  f"({rs.candidate_count} items)")

    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for err in result.errors[:20]:
            print(f"    {err}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup-storage",
        description="Clean up VS Code workspace storage bloat. DRY-RUN by default.",
    )
    # Mode
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete files. Without this flag, only a preview is shown (dry-run).")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip interactive confirmation (for CI). Only effective with --execute.")
    parser.add_argument("--confirm-each", action="store_true",
                        help="Prompt for confirmation before each individual deletion.")

    # Filtering
    parser.add_argument("--older-than", type=int, default=DEFAULT_AGE_DAYS, dest="older_than",
                        help=f"Age threshold in days (default: {DEFAULT_AGE_DAYS}).")
    parser.add_argument("--include", action="append", default=[], dest="include_cats",
                        help="Include only these cache categories (repeatable). "
                             f"Known: {', '.join(CACHE_CATEGORIES.keys())}.")
    parser.add_argument("--exclude", action="append", default=[], dest="exclude_cats",
                        help="Exclude these cache categories (repeatable).")
    parser.add_argument("--include-extensions", action="store_true",
                        help="Also clean cached extensions (not cleaned by default).")

    # Repo scoping
    parser.add_argument("--repo", action="append", default=[], dest="repos",
                        help="Only clean these repos (name substring match, repeatable).")
    parser.add_argument("--exclude-repo", action="append", default=[], dest="exclude_repos",
                        help="Exclude these repos from cleanup (repeatable).")
    parser.add_argument("--repo-regex", default=None, dest="repo_regex",
                        help="Regex pattern to filter repos.")
    parser.add_argument("--hash", action="append", default=[], dest="hashes",
                        help="Only clean workspace hashes starting with this prefix (repeatable).")

    # Output
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Emit machine-readable JSON output.")

    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Build filters
    repo_regex = re.compile(args.repo_regex, re.IGNORECASE) if args.repo_regex else None
    include_cats = set(args.include_cats) if args.include_cats else None
    exclude_cats = set(args.exclude_cats) if args.exclude_cats else None
    repo_names = set(args.repos) if args.repos else None
    exclude_repos = set(args.exclude_repos) if args.exclude_repos else None
    hash_prefixes = set(args.hashes) if args.hashes else None

    # Collect candidates
    candidates = collect_candidates(
        older_than_days=args.older_than,
        include_categories=include_cats,
        exclude_categories=exclude_cats,
        include_extensions=args.include_extensions,
        repo_names=repo_names,
        exclude_repos=exclude_repos,
        repo_regex=repo_regex,
        hash_prefixes=hash_prefixes,
    )

    if not args.execute:
        # Dry-run mode (default)
        if not args.json_output:
            print_preview(candidates)
        result = execute_cleanup(candidates, dry_run=True)
        print_result(result, as_json=args.json_output)
        if not args.json_output and candidates:
            print("  Tip: Re-run with --execute to actually delete these items.")
            print("       Add --confirm-each for per-item confirmation.\n")
        return 0

    # Execute mode: require confirmation unless --yes
    if not args.yes:
        print_preview(candidates)
        if not candidates:
            return 0
        total = sum(c.size_bytes for c in candidates)
        try:
            answer = input(
                f"\n  Confirm deletion of {len(candidates)} items "
                f"({_format_bytes(total)})? [y/N] "
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return 130
        if answer not in ("y", "yes"):
            print("  Aborted.")
            return 0

    confirm_fn: Callable[[str], bool] | None = None
    if args.yes:
        confirm_fn = lambda _desc: True  # noqa: E731

    result = execute_cleanup(
        candidates,
        dry_run=False,
        confirm_each=args.confirm_each,
        confirm_fn=confirm_fn if args.yes else None,
    )
    print_result(result, as_json=args.json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
