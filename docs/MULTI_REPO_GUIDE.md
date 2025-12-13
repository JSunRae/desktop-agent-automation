# Multi-Repo Architecture Guide

This guide describes how the desktop agent automation system operates across multiple repositories, how repositories are discovered and mapped, and how prompts and tasks are organized per repo.

## 1. High-Level Architecture

At a high level, multi-repo support is built on three pillars:

1. **Window title → repo name extraction**
   - `automation.panel_state.extract_repo_name_from_title()` parses VS Code window titles, stripping `VSCODE_TITLE_SUFFIX` (e.g., `" - Visual Studio Code"` / `" - VS Code"`).
   - The last segment before the suffix is treated as the repo identifier (e.g., `desktop-agent-automation`).

2. **Cross-repo Todo ingestion**
   - `automation.cross_repo_todo_ingestion.CrossRepoTodoIngestionService` scans sibling repos for `Todo.md` files.
   - Parsed items are written to `automation/cross_repo_todo_cache.json` and rendered to a Markdown summary for prompts.

3. **Per-repo prompt scheduling**
   - `automation.panel_tracker_core.PanelTracker` maintains `repo_prompt_indices` keyed by normalized repo name.
   - `automation.panel_task_dispatcher` + `automation.panel_seeding` use these indices and repo keys to assign follow-up prompts to panels from matching repos.

The net effect: each VS Code repo window gets its own task feed and prompt rotation, while the master orchestrator has a cross-repo view of priorities via Todo files.

---

## 2. Repository Mapping Patterns

### 2.1 From VS Code windows

Window titles typically look like:

- `main.py - desktop-agent-automation - Visual Studio Code`
- `Priority: P1 – Task GCOP-RESOU… - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code`

`extract_repo_name_from_title(title)` does the following:

1. Strip any known suffix from `WINDOW_TITLE_SUFFIXES`.
2. Split the remaining string on `" - "`.
3. Take the last non-empty segment as the repo name.

Examples:

- `"main.py - desktop-agent-automation - Visual Studio Code" → "desktop-agent-automation"`
- `"Priority: P1 – Task GCOP-RESOU… - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code" → "tf_1 [WSL: Ubuntu-24.04]"` (this may map to a logical repo key used by your prompt resolver).

### 2.2 From filesystem layout

`automation.cross_repo_todo_ingestion` treats a directory as a candidate repo root if **any** of:

- Contains a `.git` directory.
- Contains `pyproject.toml` or `requirements.txt`.
- Contains a `docs/` directory.

Todo discovery for each repo root:

- Direct files: `Todo.md`, `todo.md` in the repo root.
- Docs files: `docs/Todo.md`, `docs/todo.md`, `docs/TODO.md`.

Each discovered `(repo_name, todo_path)` pair is recorded and contributes to the cross-repo snapshot.

---

## 3. Configuration Examples

### 3.1 Enabling cross-repo ingestion

Environment variables (see `docs/ARCHITECTURE.md`):

- `CROSS_REPO_TODO_ENABLED`: enable/disable ingestion (default: true).
- `CROSS_REPO_TODO_REFRESH_INTERVAL_SECONDS`: refresh cadence (default: 300).
- `CROSS_REPO_TODO_CACHE_PATH`: snapshot JSON path.
- `CROSS_REPO_TODO_SEARCH_ROOTS`: extra scan roots (JSON array or `;`-separated list).
- `CROSS_REPO_TODO_REPO_OVERRIDES`: explicit repo roots (`{"repo": "path"}` or `repo=path;...`).

Example PowerShell setup:

```powershell
$env:CROSS_REPO_TODO_ENABLED = "true"
$env:CROSS_REPO_TODO_REFRESH_INTERVAL_SECONDS = "300"
$env:CROSS_REPO_TODO_SEARCH_ROOTS = "[\"C:/code\", \"C:/workspace\"]"
$env:CROSS_REPO_TODO_REPO_OVERRIDES = "desktop-agent-automation=C:/code/desktop-agent-automation;infra=C:/code/infra"
```

### 3.2 Panel-to-repo mapping

`PanelState.repo_name` is populated in several paths:

- On Allow clicks (`PanelTracker.record_allow_click`), using `extract_repo_name_from_title(window_title)`.
- On output updates (`update_panel_output`), which refreshes `repo_name` from the latest window title.

`PanelTracker` then uses a normalized repo key to:

- Maintain `repo_prompt_indices` for per-repo prompt rotation.
- Provide stable keys for `panel_task_dispatcher` and `CrossRepoTodoIngestionService`.

---

## 4. Prompt File Organization

Prompt resolution is handled by `automation.prompt_resolver` and `automation.panel_task_dispatcher`. The typical recommended layout per repo is:

```text
<repo_root>/
  prompts/
    default/
      system.md
      seed_prompts.md
    experimental/
      system.md
      seed_prompts.md
  docs/
    Todo.md
```

Common patterns:

- **Per-repo system prompts**: keep high-level guidance in `prompts/default/system.md`.
- **Seed prompt batches**: group follow-up tasks in `prompts/default/seed_prompts.md`.
- **Experiment branches**: mirror structure under `prompts/experimental/` and switch via config.

`panel_task_dispatcher` and `panel_seeding` load prompt blocks via helper functions such as:

- `load_prompt_blocks_for_repo(repo_name)`.
- `_resolve_prompt_path_for_repo(repo_name)` in `panel_seeding`.

Each repo key is mapped to a concrete prompt path, typically by name or via explicit overrides in your environment or `config.json`.

---

## 5. Isolation and Verification

### 5.1 Verifying Todo discovery

Use the `CrossRepoTodoIngestionService` directly:

```powershell
python - << 'EOF'
from pathlib import Path
from automation.cross_repo_todo_ingestion import CrossRepoTodoIngestionService

workspace_root = Path(".").resolve()
cache_path = workspace_root / "automation" / "cross_repo_todo_cache.json"
service = CrossRepoTodoIngestionService(
    workspace_root=workspace_root,
    cache_path=cache_path,
    refresh_interval_seconds=0,
    search_roots=[workspace_root.parent],
    repo_overrides={},
)

snapshot = service.refresh()
print("Repos discovered:", [r.repo_name for r in snapshot.repos])
for repo in snapshot.repos:
    print("-", repo.repo_name, "items:", len(repo.items))
EOF
```

### 5.2 Verifying per-repo prompt indices

```powershell
python - << 'EOF'
from automation.panel_tracker_core import PanelTracker

tracker = PanelTracker()
for repo_key, counter in tracker.repo_prompt_indices.items():
    print(repo_key, "->", counter)
EOF
```

- Trigger some finished panel processing and re-run to see counters advance.

### 5.3 Ensuring isolation between repos

Checklist:

1. Open two VS Code windows pointing at **different repos**.
2. Trigger Allow clicks and follow-ups independently.
3. Confirm in logs/metrics that:
   - `panel_title` and `repo` fields match the expected window.
   - Prompts seeded into one repo do **not** affect the other’s panels.

If cross-contamination is observed:

- Check window titles and ensure they uniquely identify repos.
- Verify that `extract_repo_name_from_title` is returning distinct names.
- Adjust naming conventions or add explicit overrides to the prompt resolver.

---

## 6. Recommended Repo Naming Conventions

To make automated mapping robust:

- Keep repo names short and consistent, e.g., `desktop-agent-automation`, `infra`, `api-gateway`.
- Avoid embedding environment details (like `[WSL: Ubuntu-24.04]`) in the final segment of the VS Code title when possible.
- If unavoidable, teach the prompt resolver how to normalize such names (e.g., strip `[WSL: ...]`).

By aligning window titles, filesystem layout, and prompt directories, the multi-repo architecture remains stable even as new projects are added to the workspace.
