# Todo - Desktop Agent Automation

## Status Snapshot

Planning artifacts were reconciled on 2026-05-14 against the current repository state.

- Full validation gate on 2026-05-14 passed: `311 passed, 7 deselected, 4 warnings in 22.99s`.
- Focused orchestration and pilot validation slices are green on the current branch, including:
	- `tests/test_orchestration_v1_discovery.py::test_orchestration_v1_reports_collector_enriched_status_rejections_in_discovery_diagnostics`
	- `tests/test_orchestration_v1_pilot_flow.py::test_duplicate_candidates_are_rejected_with_observable_metadata`
- The April 2026 full-suite and orchestration-only pass counts remain historical reconciliation evidence, not the current branch-state summary.
- Verified the agent dashboard JSON contract and the registered `master --run agent-dashboard` workflow render without runtime errors.
- Verified all-repo readiness is green under the documented contracts-only `MASTER_AGENT_REPO_CONFIGS` override.
- Verified WSL-backed document discovery for `TF` and `Trading`, with cache snapshots written under `state/docs_cache/`.
- Verified current pilot allowlist diagnostics from the managed-workspace registry audit and the new orchestration_v1 golden-path coverage.
- Closed the pilot allowlist calibration decision: keep the narrow policy with phrase-level schema and database migration blockers plus staged rollout guardrails.
- Verified recurring Copilot usage monitoring is now wired into the main automation loop behind explicit scheduling controls.
- Verified exact-window trading pilot targeting and readiness in the fresh pass; `ready_to_send=true` is still the only green state before live dispatch.
- In-repo blockers found in the fresh pass: none.
- External environment blocker: the local OpenAI credential check still fails with `401 invalid_api_key`.
- Removed stale roadmap items that duplicated already-shipped work from the finished-panels phase.

## Completed During Reconciliation

- [x] Replace markdown-bullet-only orchestration_v1 work discovery with enriched structured ingestion, per-source mismatch diagnostics, and structured JSON task ingestion
- [x] Close the finished-panel feedback seam so empty prompt feeds can trigger on-demand refresh and reseeding
- [x] Wire Copilot usage monitoring into an active recurring poller in the live automation loop
- [x] Harden the WSL-to-Windows document path boundary with doc-cache fallback and cache writes on successful reads
- [x] Add orchestration_v1 end-to-end integration coverage for dispatch, worker-response, and no-eligible-item flows
- [x] Ship the agent dashboard JSON/live CLI surface and register it under `master --run agent-dashboard`
- [x] Expand the multi-repo prompt-generation path so `contracts`, `TF`, and `Trading` participate in dependency order with repo-aware prompt context

## Active Backlog

- [ ] Fix the OpenAI credentials used by `automation.master_prompt_orchestrator` so the live non-`--dry-run` refresh path can complete without `401 invalid_api_key`

## Recurring Maintenance

- [ ] Refresh cost-tracker pricing tables + any `COST_TRACKER_MODEL_RATES` overrides whenever OpenAI updates rates (monthly check via `master --run pricing-verification`; direct fallback `python scripts/verify_pricing.py --monthly-check`)
- [ ] First business day of every month: run `master --run pricing-verification`, review the saved diff report in `logs/pricing_checks/`, update `DEFAULT_MODEL_RATES` and any runtime overrides if needed, then commit the pricing change alongside the report artifacts

## Handover References

- `HANDOVER.md` is the current repo-local handover and next-action list.
- `HANDOVER_COMPLETE.md` is a historical finished-panels archive and should not be used as the current roadmap.

## Historical Reconciliation Log

- 2026-04-25: closed seven landed workstreams in one reconciliation pass: enriched orchestration_v1 discovery, finished-panel feedback seam, recurring Copilot usage polling, WSL doc-cache fallback, orchestration_v1 end-to-end coverage, agent dashboard CLI/live view, and multi-repo prompt generation for `contracts` -> `TF` -> `Trading`; verified `275 passed, 7 deselected` for `tests/`, `68 passed, 245 deselected` for `-m orchestration`, confirmed dashboard rendering, and recorded the remaining blockers for `contracts/docs` and the invalid OpenAI API key.
- 2026-04-24: closed stale plan items for panel transcript persistence, cross-repo Todo ingestion, and adaptive agent selection after verifying shipped code and tests.
- 2026-04-25: closed Copilot usage monitoring after verifying the recurring monitor loop in `automation/orchestrator.py`, config flags in `automation/config.py`, and runtime-loop coverage in `tests/test_orchestrator_scheduling.py`.
- 2026-04-25: refined orchestration_v1 stop diagnostics so matched structured files with zero extracted task candidates are reported separately from source-pattern mismatches.
- 2026-04-25: closed source-discovery follow-through by adding per-source mismatch diagnostics and structured JSON task ingestion.
- 2026-04-25: closed Copilot usage monitor follow-through by scheduling recurring polls in the main automation loop behind explicit config.
- 2026-04-25: closed the stale README and docs-navigation cleanup after pointing active links at the current operator runbook and archived completed references.
- 2026-04-25: closed the pilot allowlist calibration stream after documenting the narrow-policy decision, calibrated blocked terms, diagnostics, regression coverage, and staged rollout guardrails in `docs/ORCHESTRATION_V1_ALLOWLIST_ROLLOUT.md`.
- 2026-04-25: closed the orchestration_v1 runtime hygiene and operator-doc alignment stream after documenting `state/orchestration/` as runtime scratch space, ignoring live dispatch and worker-report artifacts, retiring the tracked live ledger, and reserving sanitized orchestration fixtures under `tests/fixtures/orchestration_v1/`.
- 2026-04-25: removed duplicate or already-shipped roadmap items for Keep Edits confirmation, New Chat retry, seeding recovery, multi-repo support, assignment tracking, feedback loop, and cost tracking.

## Blocked Items

- Live prompt-feed refresh is currently blocked by an invalid OpenAI API key (`401 invalid_api_key`) in the local environment.
- In-repo blockers: none found in the fresh validation pass.

## Appendix: CLI prerequisites & workflow (tasks_cli.py / master.py)

This repo’s task ledger + launcher tooling relies on a local Python environment with the repo dependencies installed.

### Prerequisites

- **Python:** `>=3.11` (see `pyproject.toml` → `requires-python`)
- **Repo dependencies:** install via `requirements.txt` or editable install (recommended)

### Recommended setup (Windows / PowerShell)

```powershell
cd "<path>\desktop-agent-automation"

# Create + activate a virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Recommended: register the `master` console script
pip install -e ".[dev]"
```

### Quick smoke commands

```powershell
# Task CLI (writes to `agent_assignments.json`)
python scripts\tasks_cli.py --help

# Master launcher (two equivalent entrypoints)
master --list
python master.py --list
```

### Workflow pointer (traceability)

Follow the repo workflow in `.copilot-instructions.md`, especially the **Task Claiming** + **status update** commands using `python scripts/tasks_cli.py ...` so changes remain traceable in `agent_assignments.json`.

## Notes

- Current planning focus is the external OpenAI credential blocker above plus recurring pricing verification.
- Historical finished-panels validation is archived in `HANDOVER_COMPLETE.md`.
- Treat `state/orchestration/` as runtime scratch space, not as committed planning evidence.

---

Last updated: May 14, 2026
