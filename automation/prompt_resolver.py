from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Sequence

from automation import config

# ---------------------------------------------------------------------------
# Authoritative prompt routing state
# ---------------------------------------------------------------------------
#
# Tests and callers should patch THESE names (or the resolver functions below)
# rather than patching per-module copies.
#
# Defaults are sourced from automation.config at import time.

FINISHED_PANEL_PROMPT_PATH: Path = config.FINISHED_PANEL_PROMPT_PATH
REPO_PROMPT_MAP: Dict[str, Path] = config.REPO_PROMPT_MAP
PROMPT_FEED_FILENAME: str = getattr(
    config,
    "PROMPT_FEED_FILENAME",
    FINISHED_PANEL_PROMPT_PATH.name or "latest.txt",
)


def window_title_suffixes() -> tuple[str, ...]:
    suffixes: list[str] = []
    for candidate in (config.VSCODE_TITLE_SUFFIX, " - VS Code"):
        if candidate and candidate not in suffixes:
            suffixes.append(candidate)
    return tuple(suffixes)


def extract_repo_name_from_title(
    window_title: str,
    *,
    suffixes: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Extract the repo identifier from a VS Code window title."""
    if not window_title:
        return None

    suffixes = tuple(suffixes) if suffixes is not None else window_title_suffixes()
    normalized = window_title.strip()
    for suffix in suffixes:
        if suffix and normalized.endswith(suffix):
            core = normalized[: -len(suffix)]
            parts = [segment.strip() for segment in core.split(" - ") if segment.strip()]
            if not parts:
                return None
            candidate = parts[-1]

            # Titles may include environment markers in the repo segment.
            # Example: "ProjectA [WSL: Ubuntu-24.04]".
            candidate = re.sub(r"\s*\[WSL:[^\]]+\]\s*$", "", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"\s*\[WSL\]\s*$", "", candidate, flags=re.IGNORECASE)

            candidate = candidate.strip()
            return candidate or None
    return None


def resolve_prompt_path_for_repo(
    repo_name: Optional[str],
    *,
    default_prompt_path: Optional[Path] = None,
    repo_prompt_map: Optional[Dict[str, Path]] = None,
) -> Path:
    """Resolve which prompt feed path to use for a repo.

    Resolution order:
    1) Explicit mapping in REPO_PROMPT_MAP (case-insensitive key match).
    2) Auto-generated repo feed at: <default_prompt_path.parent>/<repo_name>/<PROMPT_FEED_FILENAME>
       (only if it exists).
    3) Fallback to default_prompt_path.

    Callers should patch `automation.prompt_resolver.REPO_PROMPT_MAP` and/or
    `automation.prompt_resolver.FINISHED_PANEL_PROMPT_PATH` for test isolation.
    """

    prompt_path = default_prompt_path or FINISHED_PANEL_PROMPT_PATH
    mapping = repo_prompt_map or REPO_PROMPT_MAP

    if repo_name:
        for configured_repo, mapped_path in mapping.items():
            if configured_repo.lower() == repo_name.lower():
                return Path(mapped_path)

        repo_specific_path = prompt_path.parent / repo_name / PROMPT_FEED_FILENAME
        if repo_specific_path.exists():
            return repo_specific_path

    return prompt_path


def resolve_prompt_path_for_window_title(
    window_title: str,
    *,
    default_prompt_path: Optional[Path] = None,
    repo_prompt_map: Optional[Dict[str, Path]] = None,
) -> Path:
    """Resolve which prompt feed path to use for a VS Code window title."""

    repo_name = extract_repo_name_from_title(window_title)
    return resolve_prompt_path_for_repo(
        repo_name,
        default_prompt_path=default_prompt_path,
        repo_prompt_map=repo_prompt_map,
    )
