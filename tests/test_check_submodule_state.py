from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_check_submodule_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "check_submodule_state.py"
    spec = importlib.util.spec_from_file_location("check_submodule_state", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discover_repo_root_prefers_git_toplevel(monkeypatch, tmp_path: Path) -> None:
    module = _load_check_submodule_module()
    repo_root = tmp_path / "repo-root"
    worktree = tmp_path / "repo-root" / "nested-worktree"

    def fake_run(args, cwd, text, capture_output, check, env):
        assert args == ["git", "rev-parse", "--show-toplevel"]
        assert cwd == str(worktree.resolve())
        assert "GIT_DIR" not in env
        return SimpleNamespace(returncode=0, stdout=str(repo_root), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    discovered = module.discover_repo_root(candidates=[worktree])

    assert discovered == repo_root.resolve()


def test_git_commands_clear_parent_git_env(monkeypatch) -> None:
    module = _load_check_submodule_module()
    observed_envs: list[dict[str, str]] = []

    def fake_run(args, cwd, text, capture_output, check, env):
        observed_envs.append(env)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("GIT_DIR", "parent/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "parent")
    monkeypatch.setenv("GIT_INDEX_FILE", "parent/index")

    module._git("status", check=False)

    assert observed_envs
    captured = observed_envs[0]
    assert "GIT_DIR" not in captured
    assert "GIT_WORK_TREE" not in captured
    assert "GIT_INDEX_FILE" not in captured
