"""
Rate limit detection in VS Code windows.

Detects rate limiting by:
- Finding "Try Again" buttons
- Searching for rate limit text patterns in panel content
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Iterable, TYPE_CHECKING, cast

import uiautomation as auto

from automation.config import (
    RATE_LIMIT_TEXT_PATTERNS,
    RATE_LIMIT_STALE_TEXT_LENGTH,
    RATE_LIMIT_PATTERN_MAX_OFFSET,
    RATE_LIMIT_PANEL_DEDUPE_MINUTES,
    RATE_LIMIT_RECENT_TEXT_WINDOW,
    RATE_LIMIT_SEGMENT_PREVIEW_CHARS,
    RATE_LIMIT_SEGMENT_MAX_COUNT,
)
from automation.ui.button_finder import find_try_again_buttons

if TYPE_CHECKING:
    pass


# ============================================================================
# PANEL CACHE FOR DEDUPLICATION
# ============================================================================

_rate_limit_panel_cache: Dict[str, datetime] = {}


def _prune_rate_limit_panel_cache(now: Optional[datetime] = None) -> None:
    """Drop cached panel identifiers that fall outside the dedupe window."""
    if RATE_LIMIT_PANEL_DEDUPE_MINUTES <= 0:
        _rate_limit_panel_cache.clear()
        return

    now = now or datetime.now()
    cutoff = now - timedelta(minutes=RATE_LIMIT_PANEL_DEDUPE_MINUTES)
    for key, seen_at in list(_rate_limit_panel_cache.items()):
        if seen_at < cutoff:
            del _rate_limit_panel_cache[key]


def _mark_rate_limit_panel_seen(panel_key: str, now: datetime) -> bool:
    """Return True if the panel is new (and mark it); False when already seen recently."""
    if RATE_LIMIT_PANEL_DEDUPE_MINUTES <= 0:
        return True

    last_seen = _rate_limit_panel_cache.get(panel_key)
    if last_seen and (now - last_seen) < timedelta(minutes=RATE_LIMIT_PANEL_DEDUPE_MINUTES):
        return False

    _rate_limit_panel_cache[panel_key] = now
    return True


# ============================================================================
# TEXT ANALYSIS HELPERS
# ============================================================================

def _earliest_rate_limit_match(normalized_text: str) -> Optional[int]:
    """Return the earliest index of any rate-limit pattern in the provided text."""
    indices = [normalized_text.find(pattern) for pattern in RATE_LIMIT_TEXT_PATTERNS]
    indices = [idx for idx in indices if idx != -1]
    if not indices:
        return None
    return min(indices)


def _is_stale_rate_limit_text(normalized_text: str, match_index: int) -> bool:
    """Heuristically determine if the match likely comes from historical chat text."""
    if RATE_LIMIT_STALE_TEXT_LENGTH <= 0:
        return False
    text_length = len(normalized_text)
    if text_length <= RATE_LIMIT_STALE_TEXT_LENGTH:
        return False
    if RATE_LIMIT_RECENT_TEXT_WINDOW > 0 and match_index >= max(0, text_length - RATE_LIMIT_RECENT_TEXT_WINDOW):
        return False
    return match_index > RATE_LIMIT_PATTERN_MAX_OFFSET


def _recent_text_window(text: str) -> tuple:
    """Return the trailing window of text plus its start index within the original string."""
    window = RATE_LIMIT_RECENT_TEXT_WINDOW
    if window <= 0 or len(text) <= window:
        return text, 0
    start = len(text) - window
    return text[start:], start


def _segment_recent_text(text: str) -> List[str]:
    """Return human-friendly previews of the latest segments inside the recent text window."""
    text = text.strip()
    if not text:
        return []

    splitter = re.compile(r"(?:\r?\n){2,}|(?:\r?\n\s*[-=*]{3,}\s*\r?\n)")
    parts = [chunk.strip() for chunk in splitter.split(text) if chunk.strip()]
    if not parts:
        parts = [chunk.strip() for chunk in text.splitlines() if chunk.strip()]

    if not parts:
        return []

    selected = parts[-RATE_LIMIT_SEGMENT_MAX_COUNT:]
    previews: List[str] = []
    for segment in selected:
        preview = segment[:RATE_LIMIT_SEGMENT_PREVIEW_CHARS]
        if len(segment) > RATE_LIMIT_SEGMENT_PREVIEW_CHARS:
            preview += "…"
        previews.append(preview)
    return previews


def _get_runtime_id(panel: auto.Control) -> Optional[str]:
    """Safely extract the runtime identifier for a UI Automation control."""
    try:
        getter = getattr(panel, "GetRuntimeId", None)
        if callable(getter):
            runtime_id = getter()
            if runtime_id and hasattr(runtime_id, "__iter__"):
                runtime_iterable = cast(Iterable[Any], runtime_id)
                runtime_parts = [str(part) for part in runtime_iterable]
                if runtime_parts:
                    return ",".join(runtime_parts)
    except Exception:
        pass

    try:
        runtime_id = getattr(panel, "RuntimeId", None)
        if runtime_id and hasattr(runtime_id, "__iter__"):
            runtime_iterable = cast(Iterable[Any], runtime_id)
            runtime_parts = [str(part) for part in runtime_iterable]
            if runtime_parts:
                return ",".join(runtime_parts)
    except Exception:
        pass
    return None


def _rate_limit_panel_identifier(
    panel: auto.Control,
    window_label: str,
    normalized_text: str,
) -> str:
    """Generate a stable identifier for a panel to suppress repeated detections."""
    runtime_key = _get_runtime_id(panel)
    if runtime_key:
        return f"rid:{window_label}:{runtime_key}"

    automation_id = ""
    try:
        automation_id = getattr(panel, "AutomationId", "") or ""
    except Exception:
        automation_id = ""

    bounds = "unknown"
    try:
        rect = panel.BoundingRectangle
        bounds = f"{rect.left}:{rect.top}:{rect.right}:{rect.bottom}"
    except Exception:
        pass

    recent_text, _ = _recent_text_window(normalized_text)
    snippet = recent_text[-160:]
    snippet_hash = hashlib.sha1(snippet.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"txt:{window_label}:{automation_id}:{bounds}:{snippet_hash}"


# ============================================================================
# DETECTION FUNCTIONS
# ============================================================================

def detect_rate_limit_in_window(vs_win: auto.Control) -> Dict[str, int]:
    """
    Return counts of Try Again buttons only (skip slow panel text scanning).
    
    Args:
        vs_win: VS Code window control
        
    Returns:
        Dict with "try_again" count and "panels" count (always 0 for speed)
    """
    try_again = len(find_try_again_buttons(vs_win))
    return {"try_again": try_again, "panels": 0}


def find_rate_limit_text_panels(
    vs_win: auto.Control,
    max_depth: int = 60,
    *,
    window_title: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[auto.Control]:
    """
    Search for visible controls whose Name matches known rate-limit messages.
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth
        window_title: Optional window title for logging
        now: Current time for cache management
        
    Returns:
        List of controls containing rate limit text
    """
    matches: List[auto.Control] = []
    now = now or datetime.now()
    _prune_rate_limit_panel_cache(now)
    window_label = (window_title or getattr(vs_win, "Name", None) or "Unknown").strip()

    def search_recursive(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth:
            return

        try:
            name = control.Name
            if name:
                normalized = name.replace("\r\n", "\n").lower()
                recent_text, window_start = _recent_text_window(normalized)
                match_relative = _earliest_rate_limit_match(recent_text)
                match_index = None if match_relative is None else window_start + match_relative
                if match_index is not None and not _is_stale_rate_limit_text(normalized, match_index):
                    if control.Exists(0.1):
                        panel_key = _rate_limit_panel_identifier(control, window_label, normalized)
                        if _mark_rate_limit_panel_seen(panel_key, now):
                            matches.append(control)

            for child in control.GetChildren():
                search_recursive(child, depth + 1)

        except Exception:
            pass

    search_recursive(vs_win)
    return matches


def get_chat_panel_text_snapshot(vs_win: auto.Control, max_depth: int = 60) -> str:
    """
    Get a snapshot of all text content in the chat panel area.
    
    Used to detect if new output is being generated (agent is working).
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth
        
    Returns:
        Concatenated text content with delimiters
    """
    text_parts: List[str] = []
    
    def collect_text(control: auto.Control, depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            name = control.Name
            if name and len(name) > 10:  # Skip short labels
                text_parts.append(name)
            for child in control.GetChildren():
                collect_text(child, depth + 1)
        except Exception:
            pass
    
    collect_text(vs_win)
    return "|||".join(text_parts)
