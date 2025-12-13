import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.master_prompt_orchestrator import MasterPromptOrchestrator, RepoConfig


class _FakeSnapshotRepo:
    def __init__(self, repo_name: str, todo_paths: list[str]):
        self.repo_name = repo_name
        self.todo_paths = todo_paths


class _FakeSnapshot:
    def __init__(self, repos: list[_FakeSnapshotRepo]):
        self.repos = repos


class FakeResponses:
    def __init__(self, text: str):
        self._text = text

    def create(self, **kwargs):  # noqa: D401 - simple stub
        return SimpleNamespace(
            output=[SimpleNamespace(type="text", text=self._text)]
        )


class FakeClient:
    def __init__(self, text: str):
        self.responses = FakeResponses(text)


class MasterPromptOrchestratorTests(unittest.TestCase):
    def test_split_prompts_parses_numbered_blocks(self):
        response_text = (
            "1. Prompt 1 (Grok): Do x\nMore details here.\n\n"
            "2. Prompt 2 (Sonnet 4.5): Do y."
        )
        prompts = MasterPromptOrchestrator._split_prompts(response_text)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(prompts[0].startswith("1. Prompt 1"))
        self.assertIn("Prompt 2", prompts[1])

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_generate_prompt_batch_creates_output(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "todo.md").write_text("- [ ] demo task", encoding="utf-8")

            repo_config = RepoConfig(name="test", docs_dirs=[docs_dir])
            orchestrator = MasterPromptOrchestrator(
                repo_configs=[repo_config],
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Grok): Do work"),
                model="test-model",
                max_docs=5,
                max_chars=200,
            )

            result = orchestrator.generate_prompt_batch()
            self.assertIsNotNone(result)
            assert result  # type narrowing for mypy/pyright
            self.assertEqual(result.prompt_count, 1)
            self.assertTrue(result.output_path.exists())
            self.assertTrue((tmp_path / "out" / "test" / "latest.txt").exists())

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_generate_prompt_batches_for_multiple_repos(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create docs for repo1
            docs_dir1 = tmp_path / "docs1"
            docs_dir1.mkdir()
            (docs_dir1 / "todo.md").write_text("- [ ] repo1 task", encoding="utf-8")
            
            # Create docs for repo2
            docs_dir2 = tmp_path / "docs2"
            docs_dir2.mkdir()
            (docs_dir2 / "todo.md").write_text("- [ ] repo2 task", encoding="utf-8")

            repo_configs = [
                RepoConfig(name="repo1", docs_dirs=[docs_dir1]),
                RepoConfig(name="repo2", docs_dirs=[docs_dir2]),
            ]
            orchestrator = MasterPromptOrchestrator(
                repo_configs=repo_configs,
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Grok): Do work for repo"),
                model="test-model",
                max_docs=5,
                max_chars=200,
            )

            results = orchestrator.generate_prompt_batches()
            self.assertEqual(len(results), 2)
            
            for result in results:
                self.assertIsNotNone(result)
                assert result  # type narrowing
                self.assertEqual(result.prompt_count, 1)
                self.assertTrue(result.output_path.exists())
                self.assertTrue((tmp_path / "out" / result.repo_name / "latest.txt").exists())

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_env_config_precedence_over_cross_repo(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env_docs = tmp_path / "env_docs"
            env_docs.mkdir()
            (env_docs / "Todo.md").write_text("- [ ] env task", encoding="utf-8")

            snapshot_docs = tmp_path / "snapshot_repo" / "docs"
            snapshot_docs.mkdir(parents=True)
            (snapshot_docs / "Todo.md").write_text("- [ ] snapshot task", encoding="utf-8")

            fake_snapshot = _FakeSnapshot([
                _FakeSnapshotRepo(
                    repo_name="snapshot_repo",
                    todo_paths=[str(snapshot_docs / "Todo.md")],
                )
            ])

            def fake_service():
                service = SimpleNamespace()
                service.get_snapshot = lambda: fake_snapshot
                return service

            orchestrator = MasterPromptOrchestrator(
                repo_configs=[RepoConfig(name="env_repo", docs_dirs=[env_docs])],
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Codex): Env task"),
                model="test-model",
                max_docs=5,
                max_chars=200,
                cross_repo_todo_service=fake_service(),
            )

            results = orchestrator.generate_prompt_batches()
            self.assertEqual(len(results), 1)
            resolved = results[0]
            self.assertIsNotNone(resolved)
            assert resolved
            self.assertEqual(resolved.repo_name, "env_repo")
            self.assertTrue((tmp_path / "out" / "env_repo" / "latest.txt").exists())
