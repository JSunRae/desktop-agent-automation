#!/usr/bin/env python3
"""Fail fast when public-tracked files cross the private/public boundary."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PATH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private env", re.compile(r"(^|/)\.env($|[./])")),
    ("private root", re.compile(r"(^|/)private/")),
    ("handover artifact", re.compile(r"^HANDOVER[^/]*\.md$", re.IGNORECASE)),
    ("panel state", re.compile(r"(^|/)automation/panel_state[^/]*\.json$", re.IGNORECASE)),
    ("session state", re.compile(r"(^|/)state/vscode_desktop_sessions[^/]*\.json$", re.IGNORECASE)),
    ("runtime state", re.compile(r"(^|/)state/")),
    ("generated prompts", re.compile(r"(^|/)tasks/generated_prompts/")),
    ("cross-repo cache", re.compile(r"(^|/)automation/cross_repo_todo_cache\.json$", re.IGNORECASE)),
    ("local log", re.compile(r"(^|/)@AutomationLog\.txt$", re.IGNORECASE)),
    ("window snapshot", re.compile(r"(^|/)window_list\.txt$", re.IGNORECASE)),
    ("coverage artifact", re.compile(r"(^|/)\.coverage$")),
)

CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private WSL path", re.compile(r"/home/jrae/", re.IGNORECASE)),
    ("private UNC path", re.compile(r"\\\\wsl\.localhost\\[^\\]+\\home\\jrae\\", re.IGNORECASE)),
    ("local Windows home", re.compile(r"[A-Za-z]:\\\\Users\\\\Pilot\\\\", re.IGNORECASE)),
    (
        "OpenAI key",
        re.compile(r"\bsk-(?:proj-[A-Za-z0-9_-]{12,}|[A-Za-z0-9_-]{20,})\b"),
    ),
    ("GitHub PAT", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]+\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+\b")),
)

CONTENT_SKIP_PREFIXES = (
    "desktop_agent_automation.egg-info/",
    "docs/completed/",
    "tests/",
)


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    detail: str


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    raw_paths = [entry for entry in result.stdout.decode("utf-8", errors="ignore").split("\0") if entry]
    return [REPO_ROOT / entry for entry in raw_paths]


def scan() -> list[Finding]:
    findings: list[Finding] = []
    for path in tracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        lowered = rel.lower()

        for label, pattern in PATH_RULES:
            if pattern.search(rel) and not lowered.endswith(".env.example"):
                findings.append(Finding("path", rel, label))
                break

        if lowered.startswith(CONTENT_SKIP_PREFIXES) or path.name.startswith("test_"):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for label, pattern in CONTENT_RULES:
            if pattern.search(text):
                findings.append(Finding("content", rel, label))
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("Public safety check passed.")
        return 0

    print("Public safety check failed:")
    for finding in findings:
        print(f"- [{finding.kind}] {finding.path}: {finding.detail}")
    print("\nMove private/runtime material to private/ or private-main before pushing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
