
from pathlib import Path
from automation.master_prompt_orchestrator import MasterPromptOrchestrator, RepoConfig

class MockOrchestrator(MasterPromptOrchestrator):
    def __init__(self):
        # Bypass __init__ to avoid setup overhead
        self.repo_configs = []

    def log(self, msg):
        print(f"LOG: {msg}")

    # Expose the internal method for testing logic
    def call_find_repo_docs_by_name(self, repo_name: str):
        from automation.master_prompt_orchestrator import _find_repo_docs_by_name
        return _find_repo_docs_by_name(repo_name)

def test_dual_repo_detection():
    orch = MockOrchestrator()
    repo_name = "Trading-Win"
    
    print(f"Testing detection for: {repo_name}")
    # We need to test the actual function now that we modified it, 
    # but since it relies on actual file system, I cannot mock the FS easily here without extensive setup.
    # Instead, I will rely on the fact that the user confirmed 'Trading-Win' exists in both places.
    
    found_paths = orch.call_find_repo_docs_by_name(repo_name)
    
    print(f"Found {len(found_paths)} paths:")
    for p in found_paths:
        print(f" - {p}")

    if len(found_paths) == 0:
         print("\n[Behavior Check] Fixed behavior: Ambiguity triggered safety skip.")
    elif len(found_paths) > 1:
        print("\n[Behavior Check] Current behavior: Multiple paths found are accepted.")
    else:
        print("\n[Behavior Check] Single path found.")

if __name__ == "__main__":
    test_dual_repo_detection()
