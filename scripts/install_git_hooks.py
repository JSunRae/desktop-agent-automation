#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_PATH = ".githooks"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    hook_file = REPO_ROOT / HOOKS_PATH / "pre-commit"
    if not hook_file.is_file():
        print(f"Missing hook file: {hook_file}")
        return 1

    enable_worktree_config = _git("config", "--local", "extensions.worktreeConfig", "true")
    if enable_worktree_config.returncode != 0:
        print(
            enable_worktree_config.stderr.strip()
            or enable_worktree_config.stdout.strip()
            or "Failed to enable worktree-specific git config"
        )
        return 1

    completed = _git("config", "--worktree", "core.hooksPath", str((REPO_ROOT / HOOKS_PATH).resolve()))
    if completed.returncode != 0:
        print(completed.stderr.strip() or completed.stdout.strip() or "Failed to configure core.hooksPath")
        return 1

    verify = _git("config", "--worktree", "--get", "core.hooksPath")
    resolved = verify.stdout.strip() if verify.returncode == 0 else ""
    print(f"Configured worktree git hooks path: {resolved or str((REPO_ROOT / HOOKS_PATH).resolve())}")
    print("Pre-commit will now block parent commits when a declared submodule has local dirty content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
