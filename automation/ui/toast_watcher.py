"""Lightweight watcher for VS Code toast notifications.

Detects Windows toast notifications emitted by VS Code (e.g., Copilot approvals)
and provides a fast path to invoke them so the focused VS Code window surfaces
immediately, letting the main loop click Allow/Keep buttons without a full scan.
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional, Tuple

import uiautomation as auto

# The toast emitted by VS Code on Windows uses XAML with these identifiers.
_TOAST_CLASSNAMES = {"FlexibleToastView"}
_TOAST_AUTOMATION_IDS = {"NormalToastView"}
_SEEN_TOASTS: dict[str, float] = {}
_SEEN_TTL_SECONDS = 120.0


def _prune_seen(now: float) -> None:
    """Drop stale toast fingerprints so the cache does not grow indefinitely."""
    stale_keys = [key for key, ts in _SEEN_TOASTS.items() if now - ts > _SEEN_TTL_SECONDS]
    for key in stale_keys:
        _SEEN_TOASTS.pop(key, None)


def _is_vscode_toast(control: auto.Control) -> bool:
    """Return True if the control looks like a VS Code toast window."""
    try:
        class_name = getattr(control, "ClassName", "") or ""
        automation_id = getattr(control, "AutomationId", "") or ""
        name = (control.Name or "").lower()
        return (
            (class_name in _TOAST_CLASSNAMES or automation_id in _TOAST_AUTOMATION_IDS)
            and "visual studio code" in name
        )
    except Exception:
        return False


def _gather_text(control: auto.Control) -> str:
    """Collect visible text from the toast and its immediate children."""
    texts: list[str] = []
    try:
        name = control.Name
        if name:
            texts.append(name.strip())
    except Exception:
        pass

    try:
        for child in control.GetChildren():
            try:
                child_name = child.Name
                if child_name:
                    texts.append(child_name.strip())
            except Exception:
                continue
    except Exception:
        pass

    # Deduplicate while preserving order
    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return "\n".join(deduped)


def _fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _invoke_toast(control: auto.Control) -> bool:
    """Best-effort click/invoke the toast."""
    try:
        inv = control.GetInvokePattern()
        if inv:
            inv.Invoke()
            return True
    except Exception:
        pass

    try:
        legacy = control.GetLegacyIAccessiblePattern()
        if legacy:
            legacy.DoDefaultAction()
            return True
    except Exception:
        pass

    return False


def try_consume_vscode_toast() -> Tuple[bool, Optional[str]]:
    """Detect and invoke a VS Code toast notification once.

    Returns:
        (handled, text): handled=True if a toast was invoked; text contains
        the collected toast text when available.
    """
    now = time.time()
    _prune_seen(now)

    try:
        root = auto.GetRootControl()
    except Exception:
        return False, None

    try:
        children = root.GetChildren()
    except Exception:
        return False, None

    for ctrl in children:
        try:
            if not _is_vscode_toast(ctrl):
                continue

            text = _gather_text(ctrl)
            key = _fingerprint(text or getattr(ctrl, "Name", "") or repr(ctrl))
            if key in _SEEN_TOASTS:
                continue

            invoked = _invoke_toast(ctrl)
            _SEEN_TOASTS[key] = now
            if invoked:
                return True, text
        except Exception:
            continue

    return False, None
