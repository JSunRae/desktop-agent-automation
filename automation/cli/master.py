"""Unified launcher for curated desktop automation workflows."""

from __future__ import annotations

import argparse
import socket
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
    category: str = "Other"
    use_python: bool = True
    cwd: Path | None = None
    options: tuple["InteractiveOption", ...] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "title": self.title,
            "category": self.category,
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
        category="Automation",
        title="Standard Automation (Modular)",
        args=("run_automation.py",),
        description="Scans windows and clicks 'Allow'/'Keep Edits' (all desktops).",
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
        key="desktop-auto-allow",
        category="Automation",
        title="Vision-based Automation (AI)",
        args=("-m", "automation.desktop_auto_allow_agent"),
        description="Vision-based (OpenAI) button detection. More robust, higher cost.",
    ),
    CommandSpec(
        key="master-prompt-orchestrator",
        category="Orchestration",
        title="Prompt Orchestrator",
        args=("-m", "automation.master_prompt_orchestrator"),
        description="Manages prompt batches, uploads docs, tracks agent progress.",
    ),
    CommandSpec(
        key="prompt-tester",
        category="Orchestration",
        title="Prompt Pack Tester",
        args=("-m", "automation.new_chat_prompt_tester"),
        description="Validates prompt batches and chat extraction logic.",
    ),
    CommandSpec(
        key="metrics-dashboard",
        category="Analytics",
        title="Live Performance Dashboard",
        args=("scripts/generate_metrics_report.py", "--mode", "dashboard"),
        description="Live telemetry: allow rates, rate limits, agent activity.",
    ),
    CommandSpec(
        key="metrics-export",
        category="Analytics",
        title="Export Telemetry Report",
        args=("scripts/generate_metrics_report.py", "--mode", "export"),
        description="Generates consolidated report of automation activity.",
    ),
    CommandSpec(
        key="cost-report",
        category="Analytics",
        title="Financial Usage Report",
        args=("scripts/cost_report.py",),
        description="Analyzes OpenAI API spend and token usage.",
    ),
    CommandSpec(
        key="align-panels",
        category="Utilities",
        title="Align VS Code Windows",
        args=("scripts/align_panels.py",),
        description="Snaps VS Code windows/panels to optimal positions.",
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
        key="test-chat-extraction",
        category="Testing",
        title="Test: Chat Extraction",
        args=("-m", "pytest", "tests/test_chat_extraction.py"),
        description="Pytest target covering extraction helpers.",
    ),
    CommandSpec(
        key="test-click-verification",
        category="Testing",
        title="Test: Click Logic",
        args=("-m", "pytest", "tests/test_click_verification.py"),
        description="Guardrails for click verification heuristics.",
    ),
    CommandSpec(
        key="test-master-orchestrator",
        category="Testing",
        title="Test: Orchestrator",
        args=("-m", "pytest", "tests/test_master_prompt_orchestrator.py"),
        description="Unit tests for prompt batch orchestrator.",
    ),
    CommandSpec(
        key="test-try-again",
        category="Testing",
        title="Test: 'Try Again' Button",
        args=("-m", "pytest", "tests/test_try_again_button.py"),
        description="Regression tests for Try Again button.",
    ),
    CommandSpec(
        key="test-vscode-detection",
        category="Testing",
        title="Test: Window Detection",
        args=("-m", "pytest", "tests/test_vscode_detection.py"),
        description="Tests VS Code window detection heuristics.",
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

    # Calculate alignment padding
    max_len = 0
    for spec in COMMANDS:
        length = len(f"{spec.title} [{spec.key}]")
        if length > max_len:
            max_len = length
    
    label_width = max_len + 2  # slight visual padding

    print(f"Found {len(COMMANDS)} workflows:")

    current_category = None
    width = len(str(len(COMMANDS)))
    for index, spec in enumerate(COMMANDS, start=1):
        if spec.category != current_category:
            if current_category is not None:
                print()
            print(f"--- {spec.category} ---")
            current_category = spec.category
        
        label = f"{spec.title} [{spec.key}]"
        try:
            print(f"{index:>{width}}. {label:<{label_width}} - {spec.description}")
        except Exception as e:
            print(f"{index:>{width}}. {label} (Error printing description: {e})")


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
    try:
        completed = subprocess.run(invocation, cwd=spec.cwd or None, check=False)
        return int(completed.returncode)
    except KeyboardInterrupt:
        # The child process will receive the signal too.
        # We just want to exit master cleanly without a traceback.
        return 130


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


def _strip_passthrough(args: Sequence[str]) -> Sequence[str]:
    """Remove known noise args like --dry-run if passed through."""
    return [a for a in args if a not in ("--dry-run",)]


def _ensure_orchestrator() -> None:
    """Check if the Telegram Orchestrator is running, and start it if not."""
    TBS_HOST = "127.0.0.1"
    TBS_PORT = 8777
    
    # Check if port is open
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((TBS_HOST, TBS_PORT)) == 0:
                # print(f"[master] Orchestrator running at {TBS_HOST}:{TBS_PORT}")
                return
    except Exception:
        pass

    print(f"[master] Telegram Orchestrator not detected at {TBS_PORT}. Attempting to start...")

    repo_path = Path("tools/TelegramNotifications")
    app_path = repo_path / "tbs_app.py"
    
    if not app_path.exists():
        print(f"[master] Warning: Could not find Telegram Orchestrator at {app_path}. Notifications might fail.")
        return

    # Start it in background
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    out_log = log_dir / "tbs_orchestrator.log"
    err_log = log_dir / "tbs_orchestrator.err"
    
    # Load environment variables from the root .env
    # We want to ensure TBS_API_TOKEN is available to the subprocess
    from dotenv import load_dotenv, find_dotenv
    # Explicitly load from CWD which is workspace root
    load_dotenv(Path(".env"))

    try:
        f_out = open(out_log, "w", encoding="utf-8")
        f_err = open(err_log, "w", encoding="utf-8")
        
        # Pass current environment which now includes .env values
        env = os.environ.copy()

        # Prefer a project virtualenv if available (fallback to current interpreter)
        python_cmd: str
        venv_override = env.get("MASTER_VENV")
        if venv_override and Path(venv_override).exists():
            python_cmd = venv_override
        else:
            candidate = Path(".venv") / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            python_cmd = str(candidate) if candidate.exists() else sys.executable
        
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        subprocess.Popen(
            [python_cmd, "-m", "uvicorn", "tbs_app:app", "--host", TBS_HOST, "--port", str(TBS_PORT)],
            cwd=str(repo_path),
            stdout=f_out,
            stderr=f_err,
            env=env,
            creationflags=creation_flags
        )
        print(f"[master] Telegram Orchestrator started (pid hidden). Logs: {out_log}")
        
        # Give it a moment to bind
        import time
        time.sleep(2.0)
        
    except Exception as e:
        print(f"[master] Failed to start Telegram Orchestrator: {e}")


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
    # Debug: verify which file is running
    # print(f" DEBUG: automation.cli.master is running from: {__file__}")
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
        _ensure_orchestrator()
        spec = _resolve_command(args.run)
        if spec is None:
            parser.error(f"Unknown workflow: {args.run}")
        return _run_spec(spec, passthrough, args.dry_run)

    _ensure_orchestrator()
    return _interactive_menu(passthrough, args.dry_run)


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    raise SystemExit(main())