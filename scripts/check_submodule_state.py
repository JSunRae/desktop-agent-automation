#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SubmoduleState:
    path: str
    branch: str | None
    head_status: str | None
    dirty: bool
    status_lines: list[str]
    submodule_status: str | None
    review_diff: str | None


def _git(*args: str, cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "git command failed")
    return completed


def _declared_submodule_paths() -> list[str]:
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.is_file():
        return []

    completed = _git(
        "config",
        "-f",
        str(gitmodules),
        "--get-regexp",
        r"^submodule\..*\.path$",
        check=False,
    )
    if completed.returncode != 0:
        return []

    paths: list[str] = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1]:
            paths.append(parts[1].strip())
    return paths


def _submodule_state(path: str) -> SubmoduleState:
    repo_path = REPO_ROOT / path
    status_completed = _git(
        "-C",
        str(repo_path),
        "status",
        "--short",
        "--branch",
        "--untracked-files=normal",
        check=False,
    )
    status_lines = [line.rstrip() for line in status_completed.stdout.splitlines() if line.strip()]
    branch = None
    head_status = None
    worktree_lines = status_lines
    if status_lines and status_lines[0].startswith("## "):
        head_status = status_lines[0][3:].strip()
        branch = head_status.split("...", 1)[0].strip() or None
        worktree_lines = status_lines[1:]

    submodule_status = _git("submodule", "status", "--", path, check=False).stdout.strip() or None
    review_diff = _git("diff", "--submodule=log", "--", path, check=False).stdout.strip() or None
    return SubmoduleState(
        path=path,
        branch=branch,
        head_status=head_status,
        dirty=bool(worktree_lines),
        status_lines=worktree_lines,
        submodule_status=submodule_status,
        review_diff=review_diff,
    )


def _payload(paths: list[str]) -> dict[str, object]:
    states = [_submodule_state(path) for path in paths]
    dirty = [state for state in states if state.dirty]
    return {
        "repo_root": str(REPO_ROOT),
        "declared_submodules": paths,
        "dirty_submodules": [state.path for state in dirty],
        "clean": not dirty,
        "submodules": [asdict(state) for state in states],
    }


def _print_human(payload: dict[str, object]) -> None:
    submodules = payload.get("submodules", [])
    if not submodules:
        print("No declared submodules found.")
        return

    dirty_submodules = payload.get("dirty_submodules", [])
    if dirty_submodules:
        print("Dirty submodule check failed.")
    else:
        print("All declared submodules are clean.")

    for row in submodules:
        if not isinstance(row, dict):
            continue
        label = str(row.get("path") or "")
        dirty = bool(row.get("dirty"))
        state = "DIRTY" if dirty else "clean"
        branch = row.get("head_status") or row.get("branch") or "unknown"
        print(f"- {label}: {state} ({branch})")
        for line in row.get("status_lines") or []:
            print(f"    {line}")

    if dirty_submodules:
        print()
        print("Resolve the nested repo before committing the parent repo:")
        print("- Review nested changes: git -C <path> status --short --branch")
        print("- If intentional, commit or stash inside the submodule first")
        print("- If accidental, clean with: git -C <path> restore --worktree --staged .")
        print("- Re-check parent review context with: git diff --submodule=log")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate declared git submodules are clean before parent commits")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--fail-if-dirty",
        action="store_true",
        help="Exit non-zero when any declared submodule has local working tree changes",
    )
    args = parser.parse_args(argv)

    paths = _declared_submodule_paths()
    payload = _payload(paths)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)

    if args.fail_if_dirty and payload.get("dirty_submodules"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())