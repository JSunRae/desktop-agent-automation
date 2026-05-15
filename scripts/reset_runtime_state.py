#!/usr/bin/env python3
"""Preview or reset tracked runtime state files to a clean launch baseline."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_ROOT = REPO_ROOT / "state" / "runtime_state_backups"


@dataclass(frozen=True)
class ResetTarget:
    key: str
    label: str
    path: Path
    writer: Callable[[Path], None]


def _write_panel_state(path: Path) -> None:
    payload = {
        "saved_at": datetime.now().isoformat(),
        "next_prompt_index": 0,
        "repo_prompt_indices": {},
        "panels": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_metrics(path: Path) -> None:
    payload = {
        "last_updated": datetime.now().isoformat(),
        "prompt_metrics": [],
        "model_metrics": [],
        "response_feedback_metrics": [],
        "cost_metrics": [],
        "workflow_metrics": [],
        "seeding_attempt_metrics": [],
        "task_discovery_metrics": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_empty_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


TARGETS: tuple[ResetTarget, ...] = (
    ResetTarget("panel-state", "Panel state", REPO_ROOT / "automation" / "panel_state.json", _write_panel_state),
    ResetTarget("metrics", "Metrics snapshot", REPO_ROOT / "automation" / "metrics.json", _write_metrics),
    ResetTarget(
        "assignment-metrics",
        "Assignment metrics log",
        REPO_ROOT / "automation" / "assignment_metrics.jsonl",
        _write_empty_jsonl,
    ),
    ResetTarget(
        "allow-metrics",
        "Allow metrics log",
        REPO_ROOT / "automation" / "allow_metrics.jsonl",
        _write_empty_jsonl,
    ),
)


def _target_map() -> dict[str, ResetTarget]:
    return {target.key: target for target in TARGETS}


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _backup_relative_path(path: Path) -> Path:
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return Path(path.name)


def _summarize_target(target: ResetTarget) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "key": target.key,
        "label": target.label,
        "path": _relative(target.path),
        "exists": target.path.exists(),
        "size_bytes": target.path.stat().st_size if target.path.exists() else 0,
    }

    if target.key == "panel-state" and target.path.exists():
        try:
            payload = json.loads(target.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summary["error"] = str(exc)
            return summary
        panels = payload.get("panels", {}) if isinstance(payload, dict) else {}
        saved_at = payload.get("saved_at") if isinstance(payload, dict) else None
        summary["panel_count"] = len(panels) if isinstance(panels, dict) else 0
        summary["saved_at"] = saved_at
        return summary

    if target.key == "metrics" and target.path.exists():
        try:
            payload = json.loads(target.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summary["error"] = str(exc)
            return summary
        summary["last_updated"] = payload.get("last_updated") if isinstance(payload, dict) else None
        summary["prompt_metric_count"] = len(payload.get("prompt_metrics", [])) if isinstance(payload, dict) else 0
        summary["response_metric_count"] = (
            len(payload.get("response_feedback_metrics", [])) if isinstance(payload, dict) else 0
        )
        return summary

    if target.path.exists():
        try:
            line_count = len([line for line in target.path.read_text(encoding="utf-8").splitlines() if line.strip()])
        except OSError as exc:
            summary["error"] = str(exc)
            return summary
        summary["line_count"] = line_count
    return summary


def _backup_target(target: ResetTarget, backup_root: Path) -> Path | None:
    if not target.path.exists():
        return None
    destination = backup_root / _backup_relative_path(target.path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target.path, destination)
    return destination


def _render_human(summaries: Sequence[dict[str, Any]], *, execute: bool, backup_root: Path | None) -> None:
    mode = "execute" if execute else "dry-run"
    print(f"Runtime state reset ({mode})")
    for summary in summaries:
        print(f"- {summary['label']}: {summary['path']}")
        if "panel_count" in summary:
            print(f"  panels={summary.get('panel_count', 0)} saved_at={summary.get('saved_at')}")
        elif "prompt_metric_count" in summary:
            print(
                "  prompt_metrics="
                f"{summary.get('prompt_metric_count', 0)} response_metrics={summary.get('response_metric_count', 0)} "
                f"last_updated={summary.get('last_updated')}"
            )
        elif "line_count" in summary:
            print(f"  non-empty lines={summary.get('line_count', 0)}")
        elif not summary.get("exists"):
            print("  file missing; clean baseline will be created on execute")
        if summary.get("error"):
            print(f"  warning: {summary['error']}")
    if execute and backup_root is not None:
        print(f"Backups written under {backup_root}")
    elif not execute:
        print("Use --execute to write the clean baseline and store backups under state/runtime_state_backups/.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview or reset tracked runtime state files")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the clean baseline instead of printing the reset plan",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable summary",
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=sorted(_target_map().keys()),
        default=[target.key for target in TARGETS],
        help="Subset of runtime-state targets to reset (default: all tracked runtime-state files)",
    )
    args = parser.parse_args(argv)

    targets = [_target_map()[key] for key in args.targets]
    summaries = [_summarize_target(target) for target in targets]

    backup_root: Path | None = None
    if args.execute:
        backup_root = DEFAULT_BACKUP_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
        for target in targets:
            _backup_target(target, backup_root)
            target.writer(target.path)

    if args.json:
        print(
            json.dumps(
                {
                    "repo_root": str(REPO_ROOT),
                    "mode": "execute" if args.execute else "dry-run",
                    "targets": summaries,
                    "backup_root": str(backup_root) if backup_root else None,
                },
                indent=2,
            )
        )
    else:
        _render_human(summaries, execute=args.execute, backup_root=backup_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
