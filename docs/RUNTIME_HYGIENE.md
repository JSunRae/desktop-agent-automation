# Runtime Hygiene

This repo mixes source code, operator documentation, historical archives, and local runtime state. Keep the boundary explicit so status reviews stay focused on real source changes.

## Path Categories

### Source of record: keep tracked

- `automation/*.py`, `scripts/*.py`, tests, and repo configuration.
- Canonical operator docs under `docs/`.
- `agent_assignments.json` and other schema-backed planning inputs that serve as shared source-of-record artifacts.
- Historical references that are intentionally preserved, such as `HANDOVER_COMPLETE.md` and `docs/completed/`.
- Sanitized fixtures such as `tests/fixtures/orchestration_v1/`.

### Shared tracked operational artifacts: review intentionally

- `automation/panel_state.json` remains tracked because the repo currently treats it as a shared persisted panel-state artifact, not throwaway scratch.
- `automation/metrics.json`, `automation/assignment_metrics.jsonl`, and `automation/allow_metrics.jsonl` remain tracked because they are consumed as shared telemetry inputs.
- `automation/cross_repo_todo_cache.json` remains tracked until it is explicitly reclassified; treat it as a persisted shared snapshot, not disposable local noise.

These files may look stateful, but they are still part of the repo's current operating model. Do not convert them to ignore rules casually.

### Runtime scratch and local fallback cache: keep local, do not track

- `state/orchestration/` for dispatch envelopes, worker reports, and the live orchestration ledger.
- `state/docs_cache/` for last-known-good WSL doc snapshots.
- `state/north_star_cache.json` for cached north-star context.
- `state/workstream_coordination.json` for local workstream lifecycle state.
- `state/vscode_desktop_sessions.json` for machine-specific VS Code desktop snapshots.
- `state/state.json` for local notification/runtime session state.
- `logs/` and root-level captures such as `@AutomationLog.txt` and `window_list.txt` for local diagnostic output.

These files are useful operationally, but they are not authoritative repo history.

### Session restore state: keep local, do not track

- `state/vscode_desktop_sessions.json` is machine-specific restore state. Treat it as local scratch even if it becomes useful during debugging.

### Orchestration live ledgers: keep local, do not track

- `state/orchestration/global_ledger.jsonl` is the live orchestration ledger.
- `state/orchestration/dispatch_queue/` and `state/orchestration/worker_reports/` are live runtime handoff channels.

If a run is worth preserving, copy a sanitized sample into tracked docs or fixtures instead of committing the live artifact.

### Historical archives: track only when curated on purpose

- Completed investigation notes and archived handovers belong in `docs/completed/` or another clearly named archive location.
- If a runtime artifact becomes worth preserving, promote a curated copy into tracked docs instead of tracking the live scratch file.

## Rules

1. Prefer `state/` for runtime output, caches, and local scratch.
2. Treat `state/docs_cache/` as fallback material, not as canonical documentation.
3. Treat `state/orchestration/` as disposable runtime output, not as planning evidence.
4. Treat root-level captures such as `@AutomationLog.txt` and `window_list.txt` as local diagnostics, not review-worthy source changes.
5. If a file is both ignored and already tracked, remove it from the index with `git rm --cached` so `.gitignore` can take effect without deleting the local file.
6. If you need a stable reference artifact, copy or summarize it into `docs/` or `tests/fixtures/` rather than committing the live cache.

## Launch Baseline Reset

If tracked runtime state has become stale, preview the reset first:

```powershell
master --run reset-runtime-state
```

When you are ready to write a clean tracked baseline and store backups under `state/runtime_state_backups/`, run:

```powershell
master --run reset-runtime-state -- --execute
```

You can also target just one tracked file, for example:

```powershell
master --run reset-runtime-state -- --targets panel-state --execute
```

## Deliberately Not Reclassified Here

Some JSON files under `automation/` look generated or stateful, but they may still serve as shared inputs, baselines, or curated snapshots. Audit those separately before converting them to scratch paths. In particular, do not infer that every `automation/*.json` file is local scratch just because some stateful files now live under `state/`.
