# ADR-0002: Cross-Repo Todo Cache

## Status

Accepted

## Context

The master orchestrator needs visibility into priorities and blockers across multiple sibling repositories without fully indexing or embedding all code from those repos. We want:

- A lightweight view of `Todo.md` content across repos.
- Stable data to inject into prompts.
- Minimal runtime overhead and a simple failure mode.

## Decision

We implemented `automation.cross_repo_todo_ingestion.CrossRepoTodoIngestionService` to:

- Discover repos by scanning sibling directories and explicit overrides.
- Parse `Todo.md`/`docs/Todo.md` into structured `TodoItem` objects.
- Persist a compact JSON snapshot to `automation/cross_repo_todo_cache.json`.
- Provide a Markdown summary rendering for prompt context.

## Consequences

- The orchestrator can surface cross-repo priorities and blockers without deep integration with each repo.
- Cache corruption is non-fatal; the service simply rebuilds the snapshot on the next refresh.
- Repo boundaries are defined by filesystem layout and naming, which requires consistent conventions.
