#!/usr/bin/env python3
"""Run the default launch-readiness gate for the parent repo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_STATE_PATH = REPO_ROOT / "automation" / "panel_state.json"
ISOLATED_ENV_PATHS: dict[str, tuple[str, ...]] = {
    "AUTOMATION_METRICS_PATH": ("automation", "metrics.json"),
    "AUTOMATION_ASSIGNMENT_METRICS_PATH": ("automation", "assignment_metrics.jsonl"),
    "ALLOW_METRICS_LOG_PATH": ("automation", "allow_metrics.jsonl"),
    "ALLOW_EVENTS_PERSIST_PATH": ("automation", "allow_events.json"),
    "CROSS_REPO_TODO_CACHE_PATH": ("automation", "cross_repo_todo_cache.json"),
    "NORTH_STAR_CACHE_PATH": ("state", "north_star_cache.json"),
    "WORKSTREAM_COORDINATION_STATE_PATH": ("state", "workstream_coordination.json"),
}


@dataclass(frozen=True)
class CheckSpec:
    key: str
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    key: str
    name: str
    ok: bool
    returncode: int
    summary: str
    command: list[str] | None = None
    details: dict[str, Any] = field(default_factory=dict)
    stdout: str | None = None
    stderr: str | None = None


COMMAND_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(
        key="parent_tests",
        name="Parent repo tests",
        command=(sys.executable, "-m", "pytest", "tests"),
    ),
    CheckSpec(
        key="task_validation",
        name="Task summary validation",
        command=(sys.executable, "scripts/validate_agent_tasks.py", "--summary"),
    ),
    CheckSpec(
        key="agent_dashboard",
        name="Agent dashboard JSON",
        command=(sys.executable, "scripts/agent_dashboard.py", "--json"),
    ),
    CheckSpec(
        key="panel_quality_help",
        name="Panel quality dashboard help",
        command=(sys.executable, "scripts/panel_quality_dashboard.py", "--help"),
    ),
    CheckSpec(
        key="workstream_dashboard_help",
        name="Workstream dashboard help",
        command=(sys.executable, "scripts/workstream_dashboard.py", "--help"),
    ),
    CheckSpec(
        key="panel_health_help",
        name="Panel health checker help",
        command=(sys.executable, "scripts/health_check_panels.py", "--help"),
    ),
    CheckSpec(
        key="docs_readiness",
        name="Default docs readiness",
        command=(sys.executable, "-m", "automation.master_prompt_orchestrator", "--readiness-check", "--json"),
    ),
    CheckSpec(
        key="openai_credentials",
        name="OpenAI credential readiness",
        command=(sys.executable, "-m", "automation.master_prompt_orchestrator", "--check-openai-credentials"),
    ),
)


def _truncate(text: str | None, limit: int = 600) -> str | None:
    if not text:
        return None
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _first_nonempty(*values: str | None) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _build_isolated_env(temp_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key, relative_path in ISOLATED_ENV_PATHS.items():
        env[key] = str(temp_root.joinpath(*relative_path))
    return env


def _run_subprocess(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _run_git_clean_check() -> CheckResult:
    completed = _run_subprocess(("git", "status", "--short"))
    output = completed.stdout.strip()
    lines = [line for line in output.splitlines() if line.strip()]
    ok = completed.returncode == 0 and not lines
    summary = "working tree clean" if ok else f"working tree has {len(lines)} pending change(s)"
    return CheckResult(
        key="git_clean",
        name="Parent repo Git cleanliness",
        ok=ok,
        returncode=0 if ok else 1,
        summary=summary,
        command=["git", "status", "--short"],
        details={"pending_changes": len(lines), "sample": lines[:10]},
        stdout=_truncate(output),
        stderr=_truncate(completed.stderr),
    )


def _run_submodule_clean_check(env: dict[str, str]) -> CheckResult:
    command = (sys.executable, "scripts/check_submodule_state.py", "--json")
    completed = _run_subprocess(command, env=env)
    output = completed.stdout.strip()
    payload: dict[str, Any] | None = None
    if output:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = None

    clean = bool(payload.get("clean")) if isinstance(payload, dict) else False
    dirty_submodules = payload.get("dirty_submodules", []) if isinstance(payload, dict) else []
    summary = "all declared submodules clean" if clean else f"dirty submodules: {', '.join(dirty_submodules) or 'unknown'}"
    return CheckResult(
        key="submodule_clean",
        name="Declared submodule cleanliness",
        ok=completed.returncode == 0 and clean,
        returncode=0 if clean else 1,
        summary=summary,
        command=list(command),
        details={"dirty_submodules": dirty_submodules},
        stdout=_truncate(output),
        stderr=_truncate(completed.stderr),
    )


def inspect_panel_state(path: Path, *, max_age_days: int) -> CheckResult:
    if not path.exists():
        return CheckResult(
            key="panel_state_freshness",
            name="Tracked panel state freshness",
            ok=True,
            returncode=0,
            summary=f"{_display_path(path)} missing; treating as clean baseline",
            details={"panel_count": 0, "saved_at": None, "newest_last_scanned": None},
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult(
            key="panel_state_freshness",
            name="Tracked panel state freshness",
            ok=False,
            returncode=1,
            summary=f"could not parse {_display_path(path)}",
            details={"error": str(exc)},
        )

    saved_at_raw = raw.get("saved_at") if isinstance(raw, dict) else None
    panels = raw.get("panels", {}) if isinstance(raw, dict) else {}
    panel_count = len(panels) if isinstance(panels, dict) else 0

    saved_at = None
    if isinstance(saved_at_raw, str) and saved_at_raw:
        try:
            saved_at = datetime.fromisoformat(saved_at_raw)
        except ValueError:
            saved_at = None

    newest_last_scanned = None
    if isinstance(panels, dict):
        for panel in panels.values():
            if not isinstance(panel, dict):
                continue
            raw_last_scanned = panel.get("last_scanned")
            if not isinstance(raw_last_scanned, str) or not raw_last_scanned:
                continue
            try:
                last_scanned = datetime.fromisoformat(raw_last_scanned)
            except ValueError:
                continue
            if newest_last_scanned is None or last_scanned > newest_last_scanned:
                newest_last_scanned = last_scanned

    reference = newest_last_scanned or saved_at
    if panel_count == 0:
        ok = True
        summary = f"{_display_path(path)} already at a clean baseline"
    elif reference is None:
        ok = False
        summary = f"{_display_path(path)} has {panel_count} panel(s) but no usable freshness timestamp"
    else:
        age_days = (datetime.now(reference.tzinfo) - reference).days
        ok = age_days <= max_age_days
        if ok:
            summary = f"{_display_path(path)} has {panel_count} panel(s); newest activity is {age_days} day(s) old"
        else:
            summary = (
                f"{_display_path(path)} is stale: {panel_count} panel(s), "
                f"newest activity {age_days} day(s) old"
            )

    return CheckResult(
        key="panel_state_freshness",
        name="Tracked panel state freshness",
        ok=ok,
        returncode=0 if ok else 1,
        summary=summary,
        details={
            "panel_count": panel_count,
            "saved_at": saved_at.isoformat() if saved_at else None,
            "newest_last_scanned": newest_last_scanned.isoformat() if newest_last_scanned else None,
            "max_age_days": max_age_days,
        },
    )


def _summarize_command_output(check: CheckSpec, completed: subprocess.CompletedProcess[str]) -> tuple[str, dict[str, Any]]:
    output = _first_nonempty(completed.stdout, completed.stderr)
    details: dict[str, Any] = {}

    if completed.returncode == 0 and check.key == "parent_tests":
        for line in reversed((completed.stdout or "").splitlines()):
            stripped = line.strip()
            if stripped.startswith("=") and " passed" in stripped:
                return stripped.strip("=").strip(), details
        return "tests passed", details

    if completed.returncode == 0 and check.key == "task_validation":
        first_line = (completed.stdout or "").splitlines()[0].strip() if (completed.stdout or "").splitlines() else ""
        return first_line or "task validation passed", details

    if check.key == "agent_dashboard":
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return output or "agent dashboard command completed", details
        panels = payload.get("panels", []) if isinstance(payload, dict) else []
        details = {
            "generated_at": payload.get("generated_at"),
            "panel_count": len(panels) if isinstance(panels, list) else None,
            "last_orchestration": payload.get("last_orchestration"),
        }
        return f"agent dashboard rendered ({details['panel_count']} panel rows)", details

    if check.key == "docs_readiness":
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return output or "docs readiness completed", details
        repo_rows = payload.get("repos", []) if isinstance(payload, dict) else []
        statuses = []
        for row in repo_rows:
            if isinstance(row, dict):
                statuses.append(f"{row.get('repo_name')}={row.get('status')}")
        details = {
            "all_repos_ready": payload.get("all_repos_ready"),
            "repo_statuses": statuses,
        }
        return ", ".join(statuses) if statuses else "docs readiness evaluated", details

    if check.key.endswith("_help") and completed.returncode == 0:
        return "help command completed", details

    return output or f"{check.name} exited {completed.returncode}", details


def _run_command_check(check: CheckSpec, env: dict[str, str]) -> CheckResult:
    completed = _run_subprocess(check.command, env=env)
    summary, details = _summarize_command_output(check, completed)
    return CheckResult(
        key=check.key,
        name=check.name,
        ok=completed.returncode == 0,
        returncode=int(completed.returncode),
        summary=summary,
        command=list(check.command),
        details=details,
        stdout=_truncate(completed.stdout),
        stderr=_truncate(completed.stderr),
    )


def run_preflight(*, state_max_age_days: int) -> list[CheckResult]:
    with tempfile.TemporaryDirectory(prefix="launch-preflight-") as temp_dir:
        isolated_env = _build_isolated_env(Path(temp_dir))
        results = [
            _run_git_clean_check(),
            _run_submodule_clean_check(isolated_env),
            inspect_panel_state(PANEL_STATE_PATH, max_age_days=state_max_age_days),
        ]
        results.extend(_run_command_check(check, isolated_env) for check in COMMAND_CHECKS)
        return results


def _render_human(results: Iterable[CheckResult]) -> None:
    results = list(results)
    passed = sum(1 for result in results if result.ok)
    print("Launch preflight")
    print(f"Checks passed: {passed}/{len(results)}")
    print()
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}")
        print(f"  {result.summary}")
        if result.command:
            print(f"  command: {' '.join(result.command)}")
        if result.stderr and not result.ok:
            print(f"  stderr: {result.stderr}")
        elif result.stdout and not result.ok:
            print(f"  output: {result.stdout}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the default launch-readiness preflight gate")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human summary",
    )
    parser.add_argument(
        "--state-max-age-days",
        type=int,
        default=14,
        help="Maximum allowed age for tracked panel-state activity before the check fails (default: 14)",
    )
    args = parser.parse_args(argv)

    results = run_preflight(state_max_age_days=max(1, args.state_max_age_days))
    payload = {
        "repo_root": str(REPO_ROOT),
        "all_checks_passed": all(result.ok for result in results),
        "results": [asdict(result) for result in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _render_human(results)

    return 0 if payload["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
