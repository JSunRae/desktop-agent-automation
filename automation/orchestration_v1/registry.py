from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from automation.orchestration_v1.models import (
    ManagedRepoConfig,
    ManagedWorkspaceRegistry,
    RepoDependencyRules,
    RepoSafetyRules,
    WorkspaceConstraints,
)

_DEFAULT_TRADING_SYSTEM_ROOT = r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system"
_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "managed_workspace_registry.json"


def _expand_env_template(value: str) -> str:
    if not value:
        return value
    if "${TRADING_SYSTEM_ROOT_WIN}" in value:
        root = os.environ.get("TRADING_SYSTEM_ROOT_WIN", _DEFAULT_TRADING_SYSTEM_ROOT)
        return value.replace("${TRADING_SYSTEM_ROOT_WIN}", root)
    return os.path.expandvars(value)


def _ensure_list_str(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, (str, int, float))]


def _load_repo(raw: Dict[str, Any]) -> ManagedRepoConfig:
    safety_raw = raw.get("safety_rules") if isinstance(raw.get("safety_rules"), dict) else {}
    dep_raw = raw.get("dependencies") if isinstance(raw.get("dependencies"), dict) else {}
    return ManagedRepoConfig(
        repo_id=str(raw.get("repo_id", "")).strip(),
        root_path=_expand_env_template(str(raw.get("root_path", "")).strip()),
        purpose=str(raw.get("purpose", "")).strip(),
        instruction_files=_ensure_list_str(raw.get("instruction_files")),
        task_sources=_ensure_list_str(raw.get("task_sources")),
        handover_locations=_ensure_list_str(raw.get("handover_locations")),
        report_locations=_ensure_list_str(raw.get("report_locations")),
        validation_commands=_ensure_list_str(raw.get("validation_commands")),
        safety_rules=RepoSafetyRules(
            protected_process_patterns=_ensure_list_str(safety_raw.get("protected_process_patterns")),
            protected_signal_files=_ensure_list_str(safety_raw.get("protected_signal_files")),
            allow_paths=_ensure_list_str(safety_raw.get("allow_paths")),
            requires_explicit_approval_for=_ensure_list_str(
                safety_raw.get("requires_explicit_approval_for")
            ),
        ),
        dependencies=RepoDependencyRules(
            blocked_by=_ensure_list_str(dep_raw.get("blocked_by")),
            follow_up_targets=_ensure_list_str(dep_raw.get("follow_up_targets")),
            source_of_truth_for=_ensure_list_str(dep_raw.get("source_of_truth_for")),
        ),
    )


def load_registry(path: Path | None = None) -> ManagedWorkspaceRegistry:
    registry_path = path or _DEFAULT_REGISTRY_PATH
    payload = json.loads(registry_path.read_text(encoding="utf-8"))

    raw_constraints = payload.get("global_constraints") if isinstance(payload.get("global_constraints"), dict) else {}
    constraints = WorkspaceConstraints(
        max_active_workers_total=int(raw_constraints.get("max_active_workers_total", 2)),
        max_active_workers_per_repo=int(raw_constraints.get("max_active_workers_per_repo", 1)),
        loop_retry_limit=int(raw_constraints.get("loop_retry_limit", 3)),
        respect_repo_boundaries=bool(raw_constraints.get("respect_repo_boundaries", True)),
        prefer_structured_sources=bool(raw_constraints.get("prefer_structured_sources", True)),
        pilot_allowlist_enabled=bool(raw_constraints.get("pilot_allowlist_enabled", False)),
        pilot_allowed_task_classes=_ensure_list_str(raw_constraints.get("pilot_allowed_task_classes")),
        pilot_allowed_categories=_ensure_list_str(raw_constraints.get("pilot_allowed_categories")),
        pilot_allowed_severities=_ensure_list_str(raw_constraints.get("pilot_allowed_severities")),
        pilot_allowed_sources=_ensure_list_str(raw_constraints.get("pilot_allowed_sources")),
        pilot_blocked_title_terms=_ensure_list_str(raw_constraints.get("pilot_blocked_title_terms")),
    )

    repos_raw = payload.get("repos") if isinstance(payload.get("repos"), list) else []
    repos = [_load_repo(repo) for repo in repos_raw if isinstance(repo, dict)]

    return ManagedWorkspaceRegistry(
        workspace_id=str(payload.get("workspace_id", "managed-workspace")),
        description=str(payload.get("description", "")),
        version=int(payload.get("version", 1)),
        global_constraints=constraints,
        repos=[repo for repo in repos if repo.repo_id],
    )


def index_repos(registry: ManagedWorkspaceRegistry) -> Dict[str, ManagedRepoConfig]:
    return {repo.repo_id.lower(): repo for repo in registry.repos}
