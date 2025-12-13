"""Panel state health monitoring and repair utilities.

This script inspects `automation/panel_state.json`, validates JSON integrity,
checks for stale/orphaned panels, and performs conservative auto-repairs.

It can be run as a standalone tool or imported and called from the
orchestration loop for periodic health checks.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from automation.config import PANEL_HEALTH_STALE_DAYS
from automation import panel_tracker
from automation.panel_state import PanelStatus
from automation.ui import find_all_vscode_windows


DEFAULT_STATE_PATH = panel_tracker.PANEL_STATE_PATH


def _backup_path(base: Path, suffix: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return base.with_name(f"{base.stem}.{suffix}.{timestamp}{base.suffix}")


def _safe_load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        corrupt_backup = _backup_path(path, "corrupt")
        try:
            path.rename(corrupt_backup)
            print(f"[health_check_panels] Corrupt panel_state.json moved to {corrupt_backup}")
        except Exception:
            print("[health_check_panels] Failed to move corrupt panel_state.json")
        print(f"[health_check_panels] JSON decode error: {exc}")
        return None


def run_health_check(state_path: Optional[Path] = None, *, auto_repair: bool = True, quiet: bool = False) -> None:
    """Validate and optionally repair the panel state file.

    - Validates JSON structure and backs up corrupt files
    - Warns about panels idle for more than PANEL_HEALTH_STALE_DAYS
    - Marks orphaned panels (no matching VS Code window) as COMPLETED
    - Normalises obvious timestamp inconsistencies
    """

    path = state_path or DEFAULT_STATE_PATH
    raw = _safe_load_json(path)

    if raw is None:
        if not quiet:
            print(f"[health_check_panels] No valid panel state found at {path}")
        return

    # Create a backup before making any modifications.
    backup = _backup_path(path, "backup")
    try:
        path.rename(backup)
        with backup.open("r", encoding="utf-8") as f:
            original_contents = f.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[health_check_panels] Failed to create backup: {exc}")
        return

    # Re-write the original file so PanelTracker can load it normally.
    try:
        with path.open("w", encoding="utf-8") as f:
            f.write(original_contents)
    except Exception as exc:  # noqa: BLE001
        print(f"[health_check_panels] Failed to restore working copy from backup: {exc}")
        return

    tracker = panel_tracker.PanelTracker(state_path=path)

    now = datetime.now()
    stale_cutoff = now - timedelta(days=PANEL_HEALTH_STALE_DAYS)

    # Discover current VS Code windows for orphan detection.
    try:
        current_windows = find_all_vscode_windows()
        live_titles = {getattr(win, "Name", "") or "" for win in current_windows}
    except Exception:  # noqa: BLE001
        live_titles = set()

    repaired = False

    for panel in list(tracker.panels.values()):
        # Normalise obviously invalid timestamps.
        try:
            if panel.last_scanned < panel.first_seen:
                panel.last_scanned = panel.first_seen
                repaired = True
            if panel.last_allow_click < panel.first_seen:
                panel.last_allow_click = panel.first_seen
                repaired = True
        except Exception:
            continue

        latest_activity = max(panel.first_seen, panel.last_allow_click, panel.last_output_change, panel.last_scanned)
        if latest_activity < stale_cutoff and not quiet:
            age_days = (now - latest_activity).days
            print(
                f"[health_check_panels] WARNING: Panel '{panel.window_title[:60]}' "
                f"has been idle for {age_days} days",
            )

        # Orphan detection: no live window matches the stored title.
        if live_titles and panel.window_title not in live_titles:
            if auto_repair and panel.status not in (PanelStatus.COMPLETED, PanelStatus.STALE):
                panel.status = PanelStatus.COMPLETED
                repaired = True
                if not quiet:
                    print(
                        f"[health_check_panels] Marking orphaned panel '{panel.window_title[:60]}' as COMPLETED",
                    )

    if auto_repair and repaired:
        try:
            tracker._save_state()
            if not quiet:
                print(f"[health_check_panels] Repairs applied. Backup saved at {backup}")
        except Exception as exc:  # noqa: BLE001
            print(f"[health_check_panels] Failed to save repaired state: {exc}")
    else:
        if not quiet:
            print(f"[health_check_panels] No repairs needed. Backup saved at {backup}")


def _restore_from_backup(target: Path, backup: Path) -> None:
    if not backup.exists():
        print(f"[health_check_panels] Backup not found: {backup}")
        return

    try:
        contents = backup.read_text(encoding="utf-8")
        target.write_text(contents, encoding="utf-8")
        print(f"[health_check_panels] Restored {target} from {backup}")
    except Exception as exc:  # noqa: BLE001
        print(f"[health_check_panels] Failed to restore from backup: {exc}")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Panel state health checker")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH, help="Path to panel_state.json")
    parser.add_argument("--no-repair", action="store_true", help="Do not apply auto-repairs; report only")
    parser.add_argument("--restore", type=Path, help="Restore panel_state.json from the given backup file")

    args = parser.parse_args(argv)

    if args.restore:
        _restore_from_backup(args.state_path, args.restore)
        return

    run_health_check(state_path=args.state_path, auto_repair=not args.no_repair, quiet=False)


if __name__ == "__main__":  # pragma: no cover
    main()
