from pathlib import Path

from automation.cross_repo_todo_ingestion import (
    CrossRepoTodoSnapshot,
    RepoTodoSnapshot,
    TodoItem,
    analyze_cross_repo_dependencies,
)


def make_snapshot(repos):
    repo_snapshots = []
    for name, items in repos.items():
        repo_snapshots.append(
            RepoTodoSnapshot(
                repo_name=name,
                todo_paths=[str(Path(f"/fake/{name}/Todo.md"))],
                parsed_at="2024-01-01T00:00:00Z",
                items=items,
            )
        )
    return CrossRepoTodoSnapshot(version=1, generated_at="2024-01-01T00:00:00Z", repos=repo_snapshots)


def test_analyze_dependencies_builds_chain_and_critical_path():
    # Single repo with a simple linear dependency chain A -> B -> C
    a = TodoItem(
        text="P0 Core infra task",
        title="Core infra task",
        priority="P0",
        is_blocked=False,
        blocked_by=[],
        section=None,
    )
    b = TodoItem(
        text="P1 Feature A (blocked by core infra)",
        title="Feature A",
        priority="P1",
        is_blocked=True,
        blocked_by=["core infra"],
        section=None,
    )
    c = TodoItem(
        text="P2 Follow-up (blocked by Feature A)",
        title="Follow-up",
        priority="P2",
        is_blocked=True,
        blocked_by=["Feature A"],
        section=None,
    )

    snapshot = make_snapshot({"repo1": [a, b, c]})
    analysis = analyze_cross_repo_dependencies(snapshot)

    # Ensure all tasks are present
    assert len(analysis.tasks) == 3

    ordered_titles = [t.title for t in analysis.iter_ordered()]
    # A must appear before B, B before C in the suggested order
    assert ordered_titles.index("Core infra task") < ordered_titles.index("Feature A")
    assert ordered_titles.index("Feature A") < ordered_titles.index("Follow-up")

    critical_titles = [t.title for t in analysis.iter_critical_path()]
    # Critical path should traverse the whole chain in order
    assert critical_titles == ["Core infra task", "Feature A", "Follow-up"]


def test_analyze_dependencies_detects_cycle_across_repos():
    # Two repos with a simple cycle: A (repo1) <-> B (repo2)
    a = TodoItem(
        text="Task A (blocked by Task B)",
        title="Task A",
        priority="P1",
        is_blocked=True,
        blocked_by=["Task B"],
        section=None,
    )
    b = TodoItem(
        text="Task B (blocked by Task A)",
        title="Task B",
        priority="P1",
        is_blocked=True,
        blocked_by=["Task A"],
        section=None,
    )

    snapshot = make_snapshot({"repo1": [a], "repo2": [b]})
    analysis = analyze_cross_repo_dependencies(snapshot)

    # We should detect at least one cycle containing both tasks
    assert analysis.cycles, "Expected at least one detected cycle"
    cycle_labels = []
    for cycle in analysis.cycles:
        labels = [analysis.tasks[k].title for k in cycle if k in analysis.tasks]
        cycle_labels.append(labels)

    flattened = [title for labels in cycle_labels for title in labels]
    assert "Task A" in flattened
    assert "Task B" in flattened
