"""Unified launcher for curated desktop automation workflows."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from automation import __version__ as PACKAGE_VERSION


@dataclass(frozen=True)
class CommandSpec:
    """Declarative definition for an operator-facing workflow."""

    key: str
    title: str
    args: tuple[str, ...]
    description: str
    use_python: bool = True
    cwd: Path | None = None
    options: tuple["InteractiveOption", ...] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "args": list(self.args),
            "use_python": self.use_python,
        }
        if self.cwd is not None:
            payload["cwd"] = str(self.cwd)
        return payload


@dataclass(frozen=True)
class InteractiveOption:
    """Interactive option that expands into additional args for a workflow."""

    key: str
    title: str
    extra_args: tuple[str, ...] = ()
    value_flag: str | None = None
    value_prompt: str | None = None


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        key="run-automation",
        title="Run Automation (New Modular)",
        args=("run_automation.py",),
        description="Launch the hotkey + panel automation orchestrator with modular routing.",
        options=(
            InteractiveOption(
                key="1",
                title="Launch immediately",
            ),
            InteractiveOption(
                key="2",
                title="Wait before launching",
                value_flag="--wait-minutes",
                value_prompt="Minutes to wait: ",
            ),
        ),
    ),
    CommandSpec(
        key="legacy-auto-allow",
        title="Run Auto Allow Copilot (Legacy)",
        args=("LAGACY_auto_allow_copilot.py",),
        description="Legacy Win32 clicker maintained for regression comparisons.",
    ),
    CommandSpec(
        key="desktop-auto-allow",
        title="Run Desktop Auto-Allow Agent",
        args=("-m", "automation.desktop_auto_allow_agent"),
        description="Computer-Use API agent that clicks VS Code Copilot approval buttons.",
    ),
    CommandSpec(
        key="vs-code-automation",
        title="Run VS Code Copilot Automation",
        args=("-m", "automation.vs_code_copilot_automation"),
        description="Primary VS Code chat automation loop with hotkeys and queueing.",
    ),
    CommandSpec(
        key="master-prompt-orchestrator",
        title="Run Master Prompt Orchestrator",
        args=("-m", "automation.master_prompt_orchestrator"),
        description="Idle supervisor that uploads docs and generates fresh prompt batches.",
    ),
    CommandSpec(
        key="prompt-tester",
        title="Run New Chat Prompt Tester",
        args=("-m", "automation.new_chat_prompt_tester"),
        description="Tooling to validate new Copilot prompt packs before dispatching them.",
    ),
    CommandSpec(
        key="test-chat-extraction",
        title="Run Test Chat Extraction",
        args=("-m", "pytest", "tests/test_chat_extraction.py"),
        description="Pytest target covering clipboard + UI automation extraction helpers.",
    ),
    CommandSpec(
        key="test-click-verification",
        title="Run Test Click Verification",
        args=("-m", "pytest", "tests/test_click_verification.py"),
        description="Guardrails around click verification heuristics for Copilot windows.",
    ),
    CommandSpec(
        key="test-master-orchestrator",
        title="Run Test Master Prompt Orchestrator",
        args=("-m", "pytest", "tests/test_master_prompt_orchestrator.py"),
        description="Unit tests for the orchestrator that hands out prompt batches.",
    ),
    CommandSpec(
        key="test-try-again",
        title="Run Test Try Again Button",
        args=("-m", "pytest", "tests/test_try_again_button.py"),
        description="Regression tests for the Try Again button finder and clicker.",
    ),
    CommandSpec(
        key="test-vscode-detection",
        title="Run Test VS Code Detection",
        args=("-m", "pytest", "tests/test_vscode_detection.py"),
        description="Ensures VS Code window detection heuristics stay stable.",
    ),
    CommandSpec(
        key="metrics-dashboard",
        title="Live Metrics Dashboard",
        args=("scripts/generate_metrics_report.py", "--mode", "dashboard"),
        description="Interactive telemetry dashboard with live trends, alerts, and anomaly detection.",
    ),
    CommandSpec(
        key="metrics-export",
        title="Export Metrics Report",
        args=("scripts/generate_metrics_report.py", "--mode", "export"),
        description="Generate consolidated JSON/Markdown telemetry summaries for sharing.",
    ),
    CommandSpec(
        key="align-panels",
        title="Align VS Code Panels",
        args=("scripts/align_panels.py",),
        description="Align VS Code panels to their configured positions on current or specified desktop.",
        options=(
            InteractiveOption(
                key="1",
                title="All desktops (default)",
                extra_args=("--all-desktops",),
            ),
            InteractiveOption(
                key="2",
                title="Current desktop only",
                extra_args=("--desktop", "current"),
            ),
            InteractiveOption(
                key="3",
                title="Specific desktop (prompt)",
                value_flag="--desktop",
                value_prompt="Desktop name (e.g., TF, Trading): ",
            ),
            InteractiveOption(
                key="4",
                title="Dry-run all desktops",
                extra_args=("--all-desktops", "--dry-run"),
            ),
            InteractiveOption(
                key="5",
                title="Dry-run current desktop",
                extra_args=("--desktop", "current", "--dry-run"),
            ),
        ),
    ),
    CommandSpec(
        key="cost-report",
        title="Generate Cost & Usage Report",
        args=("scripts/cost_report.py",),
        description="Run the financial analytics module for OpenAI spend insights.",
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="master",
        description="Desktop Agent Automation launcher",
        add_help=True,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available workflows and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Combine with --list to emit machine-readable JSON.",
    )
    parser.add_argument(
        "--run",
        metavar="KEY",
        help="Run the workflow specified by number or key without showing the menu.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved command instead of executing it.",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Emit JSON metadata for orchestrators that query CLI capabilities.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Arguments appended to the selected workflow (prefix with -- to terminate parsing).",
    )
    return parser


def _print_command_list(as_json: bool) -> None:
    if as_json:
        payload = [spec.as_dict() for spec in COMMANDS]
        print(json.dumps(payload, indent=2))
        return

    width = len(str(len(COMMANDS)))
    for index, spec in enumerate(COMMANDS, start=1):
        print(f"{index:>{width}}. {spec.title} [{spec.key}]")


def _describe_payload() -> dict[str, object]:
    inputs_schema = {
        "type": "object",
        "properties": {
            "list": {
                "type": "boolean",
                "description": "List available workflows",
                "default": False,
            },
            "json": {
                "type": "boolean",
                "description": "Emit workflow list as JSON",
                "default": False,
            },
            "run": {
                "type": "string",
                "description": "Workflow key or number to execute",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Print the resolved command instead of executing",
                "default": False,
            },
        },
        "required": [],
    }
    return {
        "name": "desktop-agent-master",
        "version": PACKAGE_VERSION,
        "schema_version": "cli.describe.v1",
        "inputs_schema": inputs_schema,
        "outputs_schema": {
            "type": "object",
            "properties": {"returncode": {"type": "integer"}},
        },
        "examples": [
            {"cmd": "master --list", "desc": "Show available workflows"},
            {
                "cmd": "master --run desktop-auto-allow",
                "desc": "Launch the Computer Use auto-allow agent",
            },
        ],
        "env": ["VIRTUAL_ENV", "MASTER_VENV", "TF1_LIST_TOOLS"],
        "side_effects": ["Runs automation subprocesses"],
        "workflows": [spec.as_dict() for spec in COMMANDS],
    }


def _normalize_token(token: str) -> str:
    return token.strip().lower().replace("_", "-")


def _resolve_command(token: str) -> CommandSpec | None:
    if not token:
        return None
    stripped = token.strip()
    if stripped.isdigit():
        index = int(stripped) - 1
        if 0 <= index < len(COMMANDS):
            return COMMANDS[index]
        return None

    normalized = _normalize_token(stripped)
    for spec in COMMANDS:
        if normalized == spec.key:
            return spec
    return None


def _build_invocation(spec: CommandSpec, extra_args: Iterable[str]) -> list[str]:
    command: list[str] = []
    if spec.use_python:
        command.append(sys.executable)
    command.extend(spec.args)

    for arg in extra_args:
        if arg == "--":
            continue
        command.append(arg)
    return command


def _run_spec(spec: CommandSpec, extra_args: Iterable[str], dry_run: bool) -> int:
    invocation = _build_invocation(spec, extra_args)
    printable = " ".join(invocation)
    if dry_run:
        print(f"[dry-run] {printable}")
        return 0

    print(f"[master] running: {printable}")
    completed = subprocess.run(invocation, cwd=spec.cwd or None, check=False)
    return int(completed.returncode)


def _prompt_for_extra_args() -> list[str] | None:
    try:
        raw = input("Extra args (blank for none): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[master] cancelled")
        return None
    if not raw:
        return []
    try:
        return shlex.split(raw, posix=False)
    except ValueError as exc:
        print(f"[master] Could not parse args: {exc}")
        return None


def _prompt_for_workflow_args(spec: CommandSpec) -> list[str] | None:
    """Return args to append for interactive menu invocation, or None to cancel."""
    print(f"\n[{spec.key}] {spec.title}")
    if spec.description:
        print(spec.description)

    if not spec.options:
        try:
            choice = input("Run (Enter), add args (a), or cancel (q): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n[master] cancelled")
            return None
        if choice in {"q", "quit", "exit"}:
            return None
        if choice in {"a", "args"}:
            return _prompt_for_extra_args()
        return []

    print("\nOptions:")
    for opt in spec.options:
        print(f" {opt.key}. {opt.title}")
    print(" a. Custom args")
    print(" q. Cancel")

    default_key = spec.options[0].key
    try:
        choice = input(f"Select option (Enter={default_key}): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[master] cancelled")
        return None
    if not choice:
        choice = default_key
    normalized = choice.strip().lower()
    if normalized in {"q", "quit", "exit"}:
        return None
    if normalized in {"a", "args"}:
        return _prompt_for_extra_args()

    selected: InteractiveOption | None = None
    for opt in spec.options:
        if normalized == opt.key.lower():
            selected = opt
            break
    if selected is None:
        print(f"[master] Unknown option: {choice!r}")
        return None

    extra: list[str] = list(selected.extra_args)
    if selected.value_flag and selected.value_prompt:
        try:
            value = input(selected.value_prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[master] cancelled")
            return None
        if not value:
            print("[master] No value provided")
            return None
        extra.extend([selected.value_flag, value])
    return extra


def _strip_passthrough(args: Sequence[str]) -> list[str]:
    if not args:
        return []
    if args and args[0] == "--":
        return list(args[1:])
    return list(args)


def _env_flag(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in {"", "0", "false", "no"}:
        return False
    return True


def _interactive_menu(passthrough: Sequence[str], dry_run: bool) -> int:
    _print_command_list(as_json=False)
    try:
        choice = input("Select workflow (number or key, q to quit): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[master] cancelled")
        return 130

    if choice.lower() in {"q", "quit", "exit"}:
        return 0
    spec = _resolve_command(choice)
    if spec is None:
        print(f"[master] Unknown selection: {choice!r}")
        return 1

    extra_args = list(passthrough)
    if not passthrough:
        prompted = _prompt_for_workflow_args(spec)
        if prompted is None:
            return 0
        extra_args = prompted

    return _run_spec(spec, extra_args, dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    passthrough = _strip_passthrough(args.passthrough or [])

    env_list_request = _env_flag("MASTER_LIST_TOOLS") or _env_flag("TF1_LIST_TOOLS")
    env_json_request = _env_flag("MASTER_LIST_TOOLS_JSON") or _env_flag("TF1_LIST_TOOLS_JSON")

    if args.describe:
        print(json.dumps(_describe_payload(), indent=2))
        return 0

    if args.list or env_list_request:
        _print_command_list(as_json=args.json or env_json_request)
        return 0

    if args.run:
        spec = _resolve_command(args.run)
        if spec is None:
            parser.error(f"Unknown workflow: {args.run}")
        return _run_spec(spec, passthrough, args.dry_run)

    return _interactive_menu(passthrough, args.dry_run)


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    raise SystemExit(main())