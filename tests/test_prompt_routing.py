import tempfile
import unittest
from pathlib import Path

import automation.panel_tracker as panel_tracker
import automation.prompt_resolver as prompt_resolver


class RepoPromptRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.original_map = dict(prompt_resolver.REPO_PROMPT_MAP)

        def restore_repo_map() -> None:
            prompt_resolver.REPO_PROMPT_MAP.clear()
            prompt_resolver.REPO_PROMPT_MAP.update(self.original_map)

        self.addCleanup(restore_repo_map)

        self.prompt_file = Path(self.tempdir.name) / "project_a_prompts.txt"
        self.prompt_file.write_text("Prompt 1\nDo the work", encoding="utf-8")
        prompt_resolver.REPO_PROMPT_MAP.clear()
        prompt_resolver.REPO_PROMPT_MAP["ProjectA"] = self.prompt_file

    def test_projecta_window_uses_mapped_prompt_file(self) -> None:
        window_title = "ProjectA - VS Code"
        resolved = panel_tracker.resolve_prompt_path_for_window(window_title)
        self.assertEqual(resolved, self.prompt_file)

    def test_projecta_window_uses_mapped_prompt_file_visual_studio_code_suffix(self) -> None:
        window_title = "ProjectA - Visual Studio Code"
        resolved = panel_tracker.resolve_prompt_path_for_window(window_title)
        self.assertEqual(resolved, self.prompt_file)

    def test_projecta_window_with_file_prefix_uses_mapped_prompt_file(self) -> None:
        window_title = "main.py - ProjectA - VS Code"
        resolved = panel_tracker.resolve_prompt_path_for_window(window_title)
        self.assertEqual(resolved, self.prompt_file)

    def test_projecta_window_with_wsl_marker_uses_mapped_prompt_file(self) -> None:
        window_title = "TASK: Review... - ProjectA [WSL: Ubuntu-24.04] - Visual Studio Code"
        resolved = panel_tracker.resolve_prompt_path_for_window(window_title)
        self.assertEqual(resolved, self.prompt_file)

    def test_repo_specific_auto_generated_prompts(self) -> None:
        # Clear explicit mappings to test auto-generated paths
        prompt_resolver.REPO_PROMPT_MAP.clear()
        
        # Create a fake generated prompts directory structure
        generated_dir = Path(self.tempdir.name) / "generated_prompts"
        repo_dir = generated_dir / "MyRepo"
        repo_dir.mkdir(parents=True)
        latest_file = repo_dir / "latest.txt"
        latest_file.write_text("Auto-generated prompt", encoding="utf-8")
        
        # Mock the FINISHED_PANEL_PROMPT_PATH to point to our test directory
        original_path = prompt_resolver.FINISHED_PANEL_PROMPT_PATH
        prompt_resolver.FINISHED_PANEL_PROMPT_PATH = generated_dir / "latest.txt"
        
        try:
            window_title = "MyRepo - VS Code"
            resolved = panel_tracker.resolve_prompt_path_for_window(window_title)
            self.assertEqual(resolved, latest_file)
        finally:
            prompt_resolver.FINISHED_PANEL_PROMPT_PATH = original_path
