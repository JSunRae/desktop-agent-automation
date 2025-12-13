import tempfile
import unittest
from pathlib import Path

from automation.cross_repo_todo_ingestion import discover_repo_todos, parse_todo_markdown


class CrossRepoTodoIngestionTests(unittest.TestCase):
    def test_discover_repo_todos_defaults_to_workspace_parent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace_root = root / "current"
            workspace_root.mkdir(parents=True)

            repo_a = root / "repoA"
            (repo_a / "docs").mkdir(parents=True)
            (repo_a / "docs" / "Todo.md").write_text("- [ ] A task", encoding="utf-8")

            repo_b = root / "repoB"
            repo_b.mkdir(parents=True)
            (repo_b / "requirements.txt").write_text("", encoding="utf-8")
            (repo_b / "Todo.md").write_text("- [ ] B task", encoding="utf-8")

            discovered = discover_repo_todos(
                workspace_root=workspace_root,
                search_roots=[],
                repo_overrides={},
            )
            discovered_set = {(name, Path(path).name) for name, path in discovered}

            self.assertIn(("repoA", "Todo.md"), discovered_set)
            self.assertIn(("repoB", "Todo.md"), discovered_set)

    def test_discover_repo_todos_respects_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace_root = root / "current"
            workspace_root.mkdir(parents=True)

            overridden_repo = root / "special"
            (overridden_repo / "docs").mkdir(parents=True)
            (overridden_repo / "docs" / "Todo.md").write_text("- [ ] Special task", encoding="utf-8")

            discovered = discover_repo_todos(
                workspace_root=workspace_root,
                search_roots=[],
                repo_overrides={"SPECIAL": overridden_repo},
            )
            discovered_names = {name for name, _ in discovered}
            self.assertIn("SPECIAL", discovered_names)

    def test_parse_todo_markdown_extracts_priority_and_blockers(self):
        md = """
# Todo

## P0
- [ ] [P0] Implement thing (blocked by task-123, task-456)

## Blockers
- Blocked: waiting on upstream

## Misc
- [ ] Plain bullet without priority
""".strip()
        snapshot = parse_todo_markdown(md, repo_name="repo", todo_path="/tmp/Todo.md")

        self.assertGreaterEqual(len(snapshot.items), 3)

        first = snapshot.items[0]
        self.assertEqual(first.priority, "P0")
        self.assertTrue(first.is_blocked)
        self.assertTrue(first.blocked_by)

        last = snapshot.items[-1]
        self.assertIsNone(last.priority)


if __name__ == "__main__":
    unittest.main()
