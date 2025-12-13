"""Utilities for parsing VS Code window titles.

Centralizes logic so repo extraction and VS Code title suffix handling stay
consistent across modules.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from automation.config import VSCODE_TITLE_SUFFIX


# VS Code window titles commonly end with " - Visual Studio Code" but some
# versions (or configurations) use the shorter " - VS Code".
VSCODE_TITLE_SUFFIXES: Tuple[str, ...] = tuple(
    dict.fromkeys([suffix for suffix in (VSCODE_TITLE_SUFFIX, " - VS Code") if suffix])
)

_WSL_SUFFIX_RE = re.compile(r"\s*\[WSL(?::[^\]]*)?\]\s*$")
_FILENAME_RE = re.compile(r"^.+\.[A-Za-z0-9]{1,6}$")


def is_vscode_window_title(title: str) -> bool:
    """Return True if the title looks like a VS Code top-level window."""
    if not title:
        return False
    normalized = title.strip()
    return any(normalized.endswith(suffix) for suffix in VSCODE_TITLE_SUFFIXES)


def strip_vscode_title_suffix(title: str) -> str:
    """Strip a known VS Code title suffix, if present."""
    if not title:
        return ""
    normalized = title.strip()
    for suffix in VSCODE_TITLE_SUFFIXES:
        if suffix and normalized.endswith(suffix):
            return normalized[: -len(suffix)].rstrip()
    return normalized


def extract_repo_name_from_vscode_window_title(window_title: str) -> Optional[str]:
    """Extract repo/workspace name from a VS Code window title.

    Supports both "... - Visual Studio Code" and "... - VS Code" suffixes.

    Heuristics:
    - If the core title has multiple " - " segments, treat the last as repo.
    - If the core title is a single segment, treat it as repo unless it looks
      like a filename (e.g. "main.py"), in which case return None.
    - Strip common WSL marker suffixes like "[WSL: Ubuntu-24.04]".
    """
    if not window_title:
        return None

    if not is_vscode_window_title(window_title):
        return None

    core = strip_vscode_title_suffix(window_title)
    if not core:
        return None

    parts = [segment.strip() for segment in core.split(" - ") if segment.strip()]
    if not parts:
        return None

    if len(parts) >= 2:
        candidate = parts[-1]
    else:
        candidate = parts[0]
        # When no folder/workspace is open, VS Code titles can be just the file name.
        if _FILENAME_RE.match(candidate):
            return None

    candidate = _WSL_SUFFIX_RE.sub("", candidate).strip()
    return candidate or None
