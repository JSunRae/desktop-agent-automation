from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from automation.master_prompt_orchestrator import MasterPromptOrchestrator, RepoConfig
from automation.north_star import (
    ActiveTask,
    NorthStarContext,
    RepoRole,
    _load_cached_north_star,
    get_north_star,
)
from automation.utils import probe_wsl_path


def test_probe_wsl_path_times_out_without_hanging(monkeypatch):
    unc_path = Path(r"\\wsl.localhost\Offline\missing")

    def slow_exists(self):
        time.sleep(0.2)
        return False

    monkeypatch.setattr(Path, "exists", slow_exists)

    started = time.perf_counter()
    result = probe_wsl_path(unc_path, timeout_seconds=0.05)
    elapsed = time.perf_counter() - started

    assert result is False
    assert elapsed < 0.15


def test_orchestrator_falls_back_to_cache_when_wsl_probe_fails(tmp_path, monkeypatch):
    cache_root = tmp_path / "docs_cache"
    repo_cache_dir = cache_root / "demo"
    repo_cache_dir.mkdir(parents=True)
    (repo_cache_dir / "Todo.md").write_text("- [ ] cached task", encoding="utf-8")

    monkeypatch.setattr("automation.master_prompt_orchestrator.DOCS_CACHE_ROOT", cache_root)
    monkeypatch.setattr("automation.master_prompt_orchestrator.ENABLE_WSL_DOC_CACHE", True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.CROSS_REPO_TODO_ENABLED", False)
    monkeypatch.setattr("automation.master_prompt_orchestrator._is_wsl_unc_path", lambda _path: True)

    docs_path = Path(r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs")

    def fake_probe(path, *_args, **_kwargs):
        return path != docs_path

    monkeypatch.setattr("automation.master_prompt_orchestrator.probe_wsl_path", fake_probe)

    log_messages: list[str] = []

    orchestrator = MasterPromptOrchestrator(
        repo_configs=[RepoConfig(name="demo", docs_dirs=[docs_path])],
        output_dir=tmp_path / "out",
        client=None,
        logger=log_messages.append,
        max_docs=5,
        max_chars=200,
        enable_quality_validation=False,
        enable_adaptive_complexity=False,
    )

    docs = orchestrator.collect_documents(orchestrator.repo_configs[0])

    assert any(doc.content == "- [ ] cached task" for doc in docs)
    warning = next(msg for msg in log_messages if "Repo 'demo' docs source external_docs_missing" in msg)
    assert str(docs_path) in warning
    assert f"using cached docs from {cache_root / 'demo'}" in warning
    assert "Create or restore the upstream docs directory" in warning
    assert "Expected relative path: docs." in warning


def test_orchestrator_logs_when_missing_wsl_repo_has_no_cache(tmp_path, monkeypatch):
    docs_path = Path(r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs")

    monkeypatch.setattr("automation.master_prompt_orchestrator.DOCS_CACHE_ROOT", tmp_path / "docs_cache")
    monkeypatch.setattr("automation.master_prompt_orchestrator.ENABLE_WSL_DOC_CACHE", True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.CROSS_REPO_TODO_ENABLED", False)
    monkeypatch.setattr("automation.master_prompt_orchestrator._is_wsl_unc_path", lambda _path: True)

    def fake_probe(path, *_args, **_kwargs):
        return path != docs_path

    monkeypatch.setattr("automation.master_prompt_orchestrator.probe_wsl_path", fake_probe)

    log_messages: list[str] = []
    orchestrator = MasterPromptOrchestrator(
        repo_configs=[RepoConfig(name="contracts", docs_dirs=[docs_path])],
        output_dir=tmp_path / "out",
        client=None,
        logger=log_messages.append,
        max_docs=5,
        max_chars=200,
        enable_quality_validation=False,
        enable_adaptive_complexity=False,
    )

    docs = orchestrator.collect_documents(orchestrator.repo_configs[0])

    assert docs == []
    warning = next(msg for msg in log_messages if "Repo 'contracts' docs source external_docs_missing" in msg)
    assert str(docs_path) in warning
    assert f"no cached docs available at {tmp_path / 'docs_cache' / 'contracts'}" in warning
    assert "TRADING_SYSTEM_ROOT_WIN / MASTER_AGENT_REPO_CONFIGS" in warning


def test_readiness_report_marks_repo_misconfiguration_when_cli_path_has_no_repo_root(tmp_path):
    docs_path = tmp_path / "custom-layout" / "missing-docs"
    orchestrator = MasterPromptOrchestrator(
        repo_configs=[RepoConfig(name="contracts", docs_dirs=[docs_path], config_source="cli")],
        output_dir=tmp_path / "out",
        client=None,
        max_docs=5,
        max_chars=200,
        enable_quality_validation=False,
        enable_adaptive_complexity=False,
    )

    report = orchestrator.build_repo_readiness_report(orchestrator.repo_configs[0])

    assert report.status == "repo_misconfiguration"
    assert report.seeding_ready is False
    assert report.docs_sources[0].message == (
        "Configured docs path is missing and no repo_root was supplied for repo 'contracts'."
    )


def test_readiness_report_marks_unreachable_upstream_root(tmp_path, monkeypatch):
    docs_path = Path(r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs")
    repo_root = docs_path.parent

    monkeypatch.setattr("automation.master_prompt_orchestrator.DOCS_CACHE_ROOT", tmp_path / "docs_cache")
    monkeypatch.setattr("automation.master_prompt_orchestrator._is_wsl_unc_path", lambda _path: True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.probe_wsl_path", lambda *_args, **_kwargs: False)

    orchestrator = MasterPromptOrchestrator(
        repo_configs=[
            RepoConfig(
                name="contracts",
                docs_dirs=[docs_path],
                repo_root=repo_root,
                config_source="env_config",
            )
        ],
        output_dir=tmp_path / "out",
        client=None,
        max_docs=5,
        max_chars=200,
        enable_quality_validation=False,
        enable_adaptive_complexity=False,
    )

    report = orchestrator.build_repo_readiness_report(orchestrator.repo_configs[0])

    assert report.status == "upstream_unreachable"
    assert report.cache_available is False
    assert report.docs_sources[0].issue_kind == "unreachable"
    assert report.docs_sources[0].message == f"Configured repo root is not reachable at {repo_root}."


def test_north_star_returns_cached_context_when_probe_fails(tmp_path, monkeypatch):
    cache_path = tmp_path / "north_star_cache.json"
    cached_context = NorthStarContext(
        primary_goal="Cached goal",
        primary_task_id="TASK-1",
        active_tasks=[
            ActiveTask(
                task_id="TASK-1",
                title="Cached title",
                description="Cached description",
                status="in_progress",
                priority="P0",
                repo="Trading",
            )
        ],
        repo_roles={
            "Trading": RepoRole(
                name="Trading",
                owns=["execution"],
                must_not_do=["training"],
                depends_on=["TF"],
                depended_on_by=[],
            )
        },
        dependency_order=["Trading"],
        routing_summary="Cached routing",
        loaded_at=datetime.now(timezone.utc).isoformat(),
    )

    monkeypatch.setattr("automation.north_star.NORTH_STAR_CACHE_PATH", cache_path)
    monkeypatch.setattr("automation.north_star.probe_wsl_path", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("automation.north_star._cached_context", None)
    monkeypatch.setattr("automation.north_star._cache_loaded_at", None)

    from automation.north_star import _write_cached_north_star

    _write_cached_north_star(cached_context, cache_path)

    context = get_north_star(force_refresh=True)

    assert context.primary_goal == "Cached goal"
    assert context.primary_task_id == "TASK-1"
    assert context.active_tasks[0].task_id == "TASK-1"


def test_cache_is_written_after_successful_read(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "Todo.md").write_text("- [ ] live task", encoding="utf-8")

    cache_root = tmp_path / "docs_cache"
    monkeypatch.setattr("automation.master_prompt_orchestrator.DOCS_CACHE_ROOT", cache_root)
    monkeypatch.setattr("automation.master_prompt_orchestrator.ENABLE_WSL_DOC_CACHE", True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.CROSS_REPO_TODO_ENABLED", False)
    monkeypatch.setattr("automation.master_prompt_orchestrator._is_wsl_unc_path", lambda _path: True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.probe_wsl_path", lambda *_args, **_kwargs: True)

    orchestrator = MasterPromptOrchestrator(
        repo_configs=[RepoConfig(name="demo", docs_dirs=[docs_dir])],
        output_dir=tmp_path / "out",
        client=None,
        max_docs=5,
        max_chars=200,
        enable_quality_validation=False,
        enable_adaptive_complexity=False,
    )

    docs = orchestrator.collect_documents(orchestrator.repo_configs[0])

    assert any(doc.content == "- [ ] live task" for doc in docs)
    cached_file = cache_root / "demo" / "Todo.md"
    assert cached_file.exists()
    assert cached_file.read_text(encoding="utf-8") == "- [ ] live task"

    north_star_root = tmp_path / "trading-system"
    (north_star_root / "Trading").mkdir(parents=True)
    (north_star_root / "TF").mkdir(parents=True)
    (north_star_root / "contracts").mkdir(parents=True)
    (north_star_root / "AGENTS.md").write_text("## Fast Routing Matrix\nTrading", encoding="utf-8")
    (north_star_root / "Trading" / "agent_assignments.json").write_text(
        '{"tasks": [{"id": "TASK-2", "title": "Live task", "description": "Live desc", "status": "in_progress", "priority": "P0"}] }',
        encoding="utf-8",
    )

    north_star_cache_path = tmp_path / "north_star_cache.json"
    monkeypatch.setattr("automation.north_star.NORTH_STAR_CACHE_PATH", north_star_cache_path)
    monkeypatch.setattr("automation.north_star.probe_wsl_path", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("automation.north_star.TRADING_SYSTEM_ROOT", north_star_root)
    monkeypatch.setattr("automation.north_star._WSL_BASE", north_star_root)
    monkeypatch.setattr("automation.north_star._cached_context", None)
    monkeypatch.setattr("automation.north_star._cache_loaded_at", None)

    context = get_north_star(force_refresh=True)
    cached_context = _load_cached_north_star(north_star_cache_path)

    assert context.primary_task_id == "TASK-2"
    assert cached_context is not None
    assert cached_context.primary_task_id == "TASK-2"


def test_readiness_and_cache_support_configured_file_sources(tmp_path, monkeypatch):
    repo_root = tmp_path / "contracts"
    repo_root.mkdir()
    readme = repo_root / "README.md"
    schemas_dir = repo_root / "schemas"
    schemas_dir.mkdir()
    schema_file = schemas_dir / "manifest.schema.json"

    readme.write_text("# Contracts\nRoot authority lives here.", encoding="utf-8")
    schema_file.write_text('{"title": "manifest"}', encoding="utf-8")

    cache_root = tmp_path / "docs_cache"
    monkeypatch.setattr("automation.master_prompt_orchestrator.DOCS_CACHE_ROOT", cache_root)
    monkeypatch.setattr("automation.master_prompt_orchestrator.ENABLE_WSL_DOC_CACHE", True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.CROSS_REPO_TODO_ENABLED", False)
    monkeypatch.setattr("automation.master_prompt_orchestrator._is_wsl_unc_path", lambda _path: True)
    monkeypatch.setattr("automation.master_prompt_orchestrator.probe_wsl_path", lambda *_args, **_kwargs: True)

    orchestrator = MasterPromptOrchestrator(
        repo_configs=[
            RepoConfig(
                name="contracts",
                docs_dirs=[readme, schemas_dir],
                repo_root=repo_root,
                config_source="env_config",
            )
        ],
        output_dir=tmp_path / "out",
        client=None,
        max_docs=10,
        max_chars=200,
        enable_quality_validation=False,
        enable_adaptive_complexity=False,
    )

    report = orchestrator.build_repo_readiness_report(orchestrator.repo_configs[0])
    docs = orchestrator.collect_documents(orchestrator.repo_configs[0])

    assert report.status == "live_ready"
    assert report.live_ready is True
    assert [source.live_document_count for source in report.docs_sources] == [1, 1]
    assert sorted(doc.path.name for doc in docs) == ["README.md", "manifest.schema.json"]
    assert (cache_root / "contracts" / "README.md").read_text(encoding="utf-8") == readme.read_text(encoding="utf-8")
    assert (cache_root / "contracts" / "manifest.schema.json").read_text(encoding="utf-8") == schema_file.read_text(encoding="utf-8")