"""Centralized filesystem paths for public/private automation state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return _REPO_ROOT


def _resolve(candidate: Path) -> Path:
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    return candidate.expanduser().resolve()


def resolve_repo_path(raw_path: str | os.PathLike[str] | None, *, default: Path | str) -> Path:
    if raw_path is None or not str(raw_path).strip():
        return _resolve(Path(default))
    return _resolve(Path(raw_path))


def private_root() -> Path:
    return resolve_repo_path(os.environ.get("AUTOMATION_PRIVATE_ROOT"), default=Path("private"))


def private_env_path() -> Path:
    return resolve_repo_path(
        os.environ.get("AUTOMATION_PRIVATE_ENV_PATH"),
        default=private_root() / ".env",
    )


def runtime_root() -> Path:
    return resolve_repo_path(
        os.environ.get("AUTOMATION_RUNTIME_ROOT"),
        default=private_root() / "runtime",
    )


def prompt_output_dir() -> Path:
    return resolve_repo_path(
        os.environ.get("MASTER_AGENT_PROMPT_DIR"),
        default=private_root() / "generated_prompts",
    )


def finished_panel_prompt_path() -> Path:
    return resolve_repo_path(
        os.environ.get("FINISHED_PANEL_PROMPT_PATH"),
        default=prompt_output_dir() / "latest.txt",
    )


def panel_state_path() -> Path:
    return resolve_repo_path(
        os.environ.get("PANEL_STATE_PATH"),
        default=runtime_root() / "panel_state.json",
    )


def vscode_session_state_path() -> Path:
    return resolve_repo_path(
        os.environ.get("VSCODE_SESSION_STATE_PATH"),
        default=runtime_root() / "vscode_desktop_sessions.json",
    )


def notifier_state_path() -> Path:
    return resolve_repo_path(
        os.environ.get("NOTIFIER_STATE_PATH"),
        default=runtime_root() / "state.json",
    )


def allow_metrics_log_path() -> Path:
    return resolve_repo_path(
        os.environ.get("ALLOW_METRICS_LOG_PATH"),
        default=runtime_root() / "allow_metrics.jsonl",
    )


def allow_events_persist_path() -> Path:
    return resolve_repo_path(
        os.environ.get("ALLOW_EVENTS_PERSIST_PATH"),
        default=runtime_root() / "allow_events.json",
    )


def cross_repo_todo_cache_path() -> Path:
    return resolve_repo_path(
        os.environ.get("CROSS_REPO_TODO_CACHE_PATH"),
        default=runtime_root() / "cross_repo_todo_cache.json",
    )


def _first_existing(candidates: Iterable[Path]) -> Path:
    materialized = [candidate.expanduser() for candidate in candidates]
    for candidate in materialized:
        if candidate.exists():
            return candidate.resolve()
    return materialized[0].resolve()


def default_trading_system_root() -> Path:
    return _first_existing(
        [
            repo_root().parent / "trading-system",
            repo_root().parent.parent / "trading-system",
            Path.home() / "projects" / "trading-system",
            Path.home() / "Documents" / "Projects" / "trading-system",
            Path.home() / "wsl_projects" / "trading-system",
        ]
    )


def trading_system_root() -> Path:
    return resolve_repo_path(
        os.environ.get("TRADING_SYSTEM_ROOT_WIN"),
        default=default_trading_system_root(),
    )


def load_automation_env() -> List[Path]:
    """Load the public-safe root .env first, then the private overlay .env."""
    loaded: List[Path] = []
    public_env = repo_root() / ".env"
    if public_env.is_file():
        load_dotenv(public_env, override=False)
        loaded.append(public_env)

    private_env = private_env_path()
    if private_env.is_file():
        load_dotenv(private_env, override=True)
        loaded.append(private_env)

    return loaded
