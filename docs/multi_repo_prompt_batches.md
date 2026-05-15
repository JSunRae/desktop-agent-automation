# Multi-Repo Prompt Batches

This guide explains how the master prompt orchestrator discovers repositories and how the panel task dispatcher consumes repo-specific prompt feeds.

## Overview

The orchestration pipeline now supports separate prompt batches per repository:

1. **Discovery** – the orchestrator determines which repos exist and where their docs live.
2. **Generation** – a prompt batch is written to `tasks/generated_prompts/<repo>/latest.txt`.
3. **Dispatch** – finished panels only pull prompts from the feed that matches their repo.

## Discovery Order

The orchestrator tries multiple sources until it finds at least one repository configuration:

1. `MASTER_AGENT_REPO_CONFIGS` environment variable (authoritative).
2. Cross-repo Todo snapshot (when `CROSS_REPO_TODO_ENABLED=true`). The Todo cache lists every repo with a Todo.md; the orchestrator infers each repo's `docs` directory plus its optional `docs/open_tasks` folder.
3. Legacy heuristics (foreground VS Code window → repo docs, current working directory, or the default `MASTER_AGENT_DOCS_ROOT`).

As soon as a source yields configs, later fallbacks are skipped. This guarantees that explicit configs remain in control.

### Environment Variable Format

`MASTER_AGENT_REPO_CONFIGS` accepts JSON or a semicolon-delimited string. JSON is the safer operator format because it supports `repo_root` and mixed file or directory sources per repo:

```json
[
  {
    "name": "repo1",
    "repo_root": "/path/to/repo1",
    "docs_dirs": ["/path/to/repo1/docs", "/path/to/repo1/docs/open_tasks"]
  },
  {
    "name": "repo2",
    "repo_root": "/path/to/repo2",
    "docs_dirs": ["/path/to/repo2/README.md", "/path/to/repo2/schemas"]
  }
]
```

or:

```
repo1=/path/to/repo1/docs,/path/to/repo1/docs/open_tasks;repo2=/path/to/repo2/docs
```

## Files on Disk

Each repo gets its own folder beneath `MASTER_AGENT_PROMPT_DIR` (default `tasks/generated_prompts`). Every run writes:

- `tasks/generated_prompts/<repo>/master_prompts_<timestamp>.txt`
- `tasks/generated_prompts/<repo>/latest.txt` (symlink copy for easy consumption)
- `tasks/generated_prompts/<repo>/manifest.jsonl` (append-only metadata)

These feeds are what the dispatcher reads when seeding prompts.

## Dispatcher Consumption

Finished panels include a `repo_name` derived from the VS Code window title. The dispatcher resolves prompt feeds as follows:

1. `REPO_PROMPT_MAP` entries (manual overrides) if configured.
2. `tasks/generated_prompts/<repo>/latest.txt` when present.
3. Default feed `tasks/generated_prompts/latest.txt` (optional fallback controlled by `FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK`).

If a repo feed is missing and fallback is disabled, the dispatcher logs the expected path so you can generate a batch.

## Common Workflows

- **Single repo** – no changes needed; defaults continue to work.
- **Multiple repos** – set `MASTER_AGENT_REPO_CONFIGS` and ensure each repo's docs are reachable locally. Run `python -m automation.master_prompt_orchestrator --repos repoA=/path/to/docsA repoB=/path/to/docsB` for ad-hoc generation.
- **Auto-discover siblings** – enable the cross-repo Todo service (`CROSS_REPO_TODO_ENABLED=true`) and keep the cache fresh; the orchestrator will reuse the snapshot to build prompt batches without extra configuration.

### Contracts-only override

If only `contracts` has a nonstandard layout, do not change `TRADING_SYSTEM_ROOT_WIN`. That changes the default root for `contracts`, `TF`, and `Trading` together. Use `MASTER_AGENT_REPO_CONFIGS` and declare all three repos explicitly so only `contracts` is redirected.

Validated PowerShell example:

```powershell
$env:MASTER_AGENT_REPO_CONFIGS = @'
[
  {
    "name": "contracts",
    "repo_root": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts",
    "docs_dirs": [
      "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\README.md",
      "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\contracts",
      "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\schemas",
      "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\rules",
      "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\data_formats"
    ],
    "role": "source of truth"
  },
  {
    "name": "TF",
    "repo_root": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\TF",
    "docs_dirs": ["\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\TF\\docs"],
    "role": "upstream framework"
  },
  {
    "name": "Trading",
    "repo_root": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\Trading",
    "docs_dirs": ["\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\Trading\\docs"],
    "role": "downstream live system"
  }
]
'@
```

Validation command:

```powershell
python -m automation.master_prompt_orchestrator --readiness-check --json
```

Expected result: `contracts`, `TF`, and `Trading` all report `live_ready`.

## Troubleshooting

- **"No documents found"** – confirm the doc paths exist and contain allowed file types (`.md`, `.txt`, `.py`, etc.).
- **Panels pulling wrong prompts** – check `REPO_PROMPT_MAP` overrides and the repo name extracted from the VS Code window title (see `automation.title_parsing`).
- **Need to skip UI-heavy tests** – run `pytest -m "not ui"` (UI/integration tests are marked `@pytest.mark.ui`).
