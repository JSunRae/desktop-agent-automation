import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.master_prompt_orchestrator import (
    MasterPromptOrchestrator,
    OpenAICredentialError,
    RepoConfig,
    _parse_repo_configs,
)
from automation.prompt_resolver import PROMPT_FEED_FILENAME


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


class FakeAuthError(Exception):
    pass


class FakeFailingResponses:
    def create(self, **kwargs):
        raise FakeAuthError("Error code: 401 - {'error': {'message': 'invalid_api_key'}}")


class FakeFailingClient:
    def __init__(self):
        self.responses = FakeFailingResponses()


class FakeCapturingResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output=[SimpleNamespace(type="text", text="READY")])


class FakeCapturingClient:
    def __init__(self):
        self.responses = FakeCapturingResponses()


@contextmanager
def _patched_empty_openai_env():
    with patch.dict('automation.master_prompt_orchestrator.os.environ', {}, clear=True):
        yield


class MasterPromptOrchestratorTests(unittest.TestCase):
    def test_cli_repo_configs_infer_repo_root(self):
        configs = _parse_repo_configs([
            r"contracts=\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs"
        ], [])

        self.assertEqual(len(configs), 1)
        self.assertEqual(
            configs[0].repo_root,
            Path(r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts"),
        )
        self.assertEqual(configs[0].config_source, "cli")

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
            self.assertTrue((tmp_path / "out" / "test" / PROMPT_FEED_FILENAME).exists())

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
                self.assertTrue((tmp_path / "out" / result.repo_name / PROMPT_FEED_FILENAME).exists())

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
            self.assertTrue((tmp_path / "out" / "env_repo" / PROMPT_FEED_FILENAME).exists())

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_refresh_all_feeds_respects_explicit_configs(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "todo.md").write_text("- [ ] demo task", encoding="utf-8")

            repo_config = RepoConfig(name="explicit", docs_dirs=[docs_dir])
            orchestrator = MasterPromptOrchestrator(
                repo_configs=[repo_config],
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Grok): Do work"),
                model="test-model",
                max_docs=5,
                max_chars=200,
            )

            with patch.object(orchestrator, "_discover_repo_configs") as discover:
                results = orchestrator.refresh_all_feeds(dry_run=True, force_discovery=False)
                discover.assert_not_called()

            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0])
            assert results[0]
            self.assertEqual(results[0].repo_name, "explicit")

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_refresh_all_feeds_force_discovery(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "todo.md").write_text("- [ ] demo task", encoding="utf-8")

            repo_config = RepoConfig(name="explicit", docs_dirs=[docs_dir])
            orchestrator = MasterPromptOrchestrator(
                repo_configs=[repo_config],
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Grok): Do work"),
                model="test-model",
                max_docs=5,
                max_chars=200,
            )

            forced_configs = [RepoConfig(name="forced", docs_dirs=[docs_dir])]
            with patch.object(orchestrator, "_discover_repo_configs", return_value=forced_configs) as discover:
                results = orchestrator.refresh_all_feeds(dry_run=True, force_discovery=True)
                discover.assert_called_once()

            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0])
            assert results[0]
            self.assertEqual(results[0].repo_name, "forced")

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_generate_prompt_batches_runs_credential_preflight_for_live_calls(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "todo.md").write_text("- [ ] demo task", encoding="utf-8")

            orchestrator = MasterPromptOrchestrator(
                repo_configs=[RepoConfig(name="test", docs_dirs=[docs_dir])],
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Grok): Do work"),
                model="test-model",
                max_docs=5,
                max_chars=200,
            )

            with patch.object(
                orchestrator,
                "validate_openai_credentials",
                wraps=orchestrator.validate_openai_credentials,
            ) as validate:
                results = orchestrator.generate_prompt_batches(dry_run=False)

            validate.assert_called_once()
            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0])

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_generate_prompt_batches_skips_credential_preflight_for_dry_run(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "todo.md").write_text("- [ ] demo task", encoding="utf-8")

            orchestrator = MasterPromptOrchestrator(
                repo_configs=[RepoConfig(name="test", docs_dirs=[docs_dir])],
                output_dir=tmp_path / "out",
                client=FakeClient("1. Prompt (Grok): Do work"),
                model="test-model",
                max_docs=5,
                max_chars=200,
            )

            with patch.object(orchestrator, "validate_openai_credentials") as validate:
                results = orchestrator.generate_prompt_batches(dry_run=True)

            validate.assert_not_called()
            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0])

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_generate_prompt_batch_for_repo_runs_credential_preflight_for_live_calls(self, mock_cost_tracker):
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

            with patch.object(
                orchestrator,
                "validate_openai_credentials",
                wraps=orchestrator.validate_openai_credentials,
            ) as validate:
                result = orchestrator.generate_prompt_batch_for_repo(repo_config, dry_run=False)

            validate.assert_called_once()
            self.assertIsNotNone(result)

    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    def test_generate_prompt_batch_backcompat_skips_credential_preflight_for_dry_run(self, mock_cost_tracker):
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

            with patch.object(orchestrator, "validate_openai_credentials") as validate:
                result = orchestrator.generate_prompt_batch(dry_run=True)

            validate.assert_not_called()
            self.assertIsNotNone(result)

    def test_validate_openai_credentials_reports_missing_secret_precisely(self):
        with _patched_empty_openai_env():
            orchestrator = MasterPromptOrchestrator(repo_configs=[])
            with self.assertRaises(OpenAICredentialError) as ctx:
                orchestrator.validate_openai_credentials()

        message = str(ctx.exception)
        self.assertIn("OPENAI_API_KEY is missing", message)
        self.assertIn("repo-root .env", message)

    @patch('automation.master_prompt_orchestrator.OpenAIAuthenticationError', FakeAuthError)
    def test_validate_openai_credentials_wraps_invalid_api_key(self):
        orchestrator = MasterPromptOrchestrator(repo_configs=[], client=FakeFailingClient())

        with self.assertRaises(OpenAICredentialError) as ctx:
            orchestrator.validate_openai_credentials()

        message = str(ctx.exception)
        self.assertIn("authentication failed", message)
        self.assertIn("invalid_api_key", message)

    def test_validate_openai_credentials_uses_supported_probe_size(self):
        client = FakeCapturingClient()
        orchestrator = MasterPromptOrchestrator(repo_configs=[], client=client)

        result = orchestrator.validate_openai_credentials()

        self.assertEqual(result["credential_source"], "injected client")
        self.assertEqual(len(client.responses.calls), 1)
        self.assertEqual(client.responses.calls[0]["max_output_tokens"], 16)

    @patch('automation.master_prompt_orchestrator.CROSS_REPO_TODO_ENABLED', False)
    @patch('automation.master_prompt_orchestrator._COST_TRACKER')
    @patch(
        'automation.master_prompt_orchestrator.MASTER_AGENT_REPO_CONFIGS',
        [
            {"name": "Trading", "docs_dirs": [Path("Trading/docs")], "role": "downstream live system"},
            {"name": "contracts", "docs_dirs": [Path("contracts/docs")], "role": "source of truth"},
            {"name": "TF", "docs_dirs": [Path("TF/docs")], "role": "upstream framework"},
        ],
    )
    def test_refresh_all_feeds_processes_default_repos_in_dependency_order(self, mock_cost_tracker):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_dirs = {
                "contracts": tmp_path / "contracts" / "docs",
                "TF": tmp_path / "TF" / "docs",
                "Trading": tmp_path / "Trading" / "docs",
            }
            for docs_dir in repo_dirs.values():
                docs_dir.mkdir(parents=True)
                (docs_dir / "Todo.md").write_text("- [ ] demo task", encoding="utf-8")

            patched_configs = [
                {"name": "Trading", "docs_dirs": [repo_dirs["Trading"]], "role": "downstream live system"},
                {"name": "contracts", "docs_dirs": [repo_dirs["contracts"]], "role": "source of truth"},
                {"name": "TF", "docs_dirs": [repo_dirs["TF"]], "role": "upstream framework"},
            ]

            with patch('automation.master_prompt_orchestrator.MASTER_AGENT_REPO_CONFIGS', patched_configs):
                orchestrator = MasterPromptOrchestrator(
                    output_dir=tmp_path / "out",
                    client=FakeClient("1. Prompt (Grok): Do work"),
                    model="test-model",
                    max_docs=5,
                    max_chars=200,
                )

                processed: list[str] = []
                fake_north_star = SimpleNamespace(dependency_order=["contracts", "TF", "Trading"])

                with patch.object(orchestrator, "_load_north_star_context", return_value=fake_north_star):
                    with patch.object(
                        orchestrator,
                        "generate_prompt_batch_for_repo",
                        side_effect=lambda repo_config, dry_run=False: processed.append(repo_config.name) or SimpleNamespace(repo_name=repo_config.name),
                    ):
                        results = orchestrator.refresh_all_feeds(dry_run=True, force_discovery=True)

            self.assertEqual(processed, ["contracts", "TF", "Trading"])
            self.assertEqual(len(results), 3)
