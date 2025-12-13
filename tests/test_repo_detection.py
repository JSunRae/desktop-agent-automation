"""
Test repo-root detection from VS Code window titles.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from automation.master_prompt_orchestrator import _find_repo_docs_by_name  # noqa: E402
from automation.title_parsing import extract_repo_name_from_vscode_window_title  # noqa: E402


def test_extract_repo_name():
    """Test extraction of repo name from various window title formats."""
    
    test_cases = [
        # (window_title, expected_repo_name)
        ("test.py - Trading-Win - Visual Studio Code", "Trading-Win"),
        ("TASK: Review... - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code", "tf_1"),
        ("TASK: Review... - tf_1 [WSL] - Visual Studio Code", "tf_1"),
        ("main.py - desktop-agent-automation - Visual Studio Code", "desktop-agent-automation"),
        ("Testing window functionality - desktop-agent-automation - Visual Studio Code", "desktop-agent-automation"),
        ("README.md - my-project - Visual Studio Code", "my-project"),
        ("README.md - my-project - VS Code", "my-project"),
        ("my-project - VS Code", "my-project"),
        # Edge cases
        ("Not a VS Code window", None),
        ("test.py - Visual Studio Code", None),  # Missing repo name
        ("test.py - VS Code", None),  # Missing repo name
        ("", None),
    ]
    
    print("\n" + "="*70)
    print("REPO NAME EXTRACTION TESTS")
    print("="*70 + "\n")
    
    passed = 0
    failed = 0
    
    for window_title, expected in test_cases:
        result = extract_repo_name_from_vscode_window_title(window_title)
        status = "✓" if result == expected else "✗"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} '{window_title[:50]}...'")
        print(f"   Expected: {expected}")
        print(f"   Got:      {result}")
        print()
    
    print("-" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*70 + "\n")

    assert failed == 0


def test_find_repo_docs(tmp_path, monkeypatch):
    """Test finding docs folders for known repos."""
    
    print("\n" + "="*70)
    print("REPO DOCS FINDER TESTS")
    print("="*70 + "\n")
    
    # Make this deterministic by faking a home directory layout.
    current_repo = "desktop-agent-automation"
    fake_repo_root = tmp_path / "Documents" / "Vs Code Projects" / current_repo
    docs_dir = fake_repo_root / "docs"
    open_tasks_dir = docs_dir / "open_tasks"
    open_tasks_dir.mkdir(parents=True)

    import automation.master_prompt_orchestrator as mpo

    monkeypatch.setattr(mpo.Path, "home", classmethod(lambda cls: tmp_path))

    docs_paths = _find_repo_docs_by_name(current_repo)
    
    print(f"Searching for docs in repo: {current_repo}")
    print(f"Found {len(docs_paths)} path(s):")
    for path in docs_paths:
        print(f"  • {path}")
        print(f"    Exists: {path.exists()}")
    print()
    
    assert docs_dir.resolve() in {p.resolve() for p in docs_paths}
    assert open_tasks_dir.resolve() in {p.resolve() for p in docs_paths}


if __name__ == "__main__":
    # Run as a script (pytest-style assertions will raise on failure)
    test_extract_repo_name()
    from pytest import MonkeyPatch

    mp = MonkeyPatch()
    try:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            test_find_repo_docs(Path(td), mp)
    finally:
        mp.undo()

    print("\n✅ All tests passed!")
    sys.exit(0)
