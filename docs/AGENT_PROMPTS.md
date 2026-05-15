# Agent Prompts — Desktop Agent Automation

> Last updated: May 14, 2026
> Purpose: Ready-to-paste prompts for auditing the repo, planning next work, and driving long-running agent workstreams.

---

## 0 — CURRENT VALIDATED STATUS (read this first)

Current validated state as of 2026-05-14 for the goal of centrally managing repo workstreams from one loop:

- Full repo test gate is green: `311 passed, 7 deselected, 4 warnings in 22.99s`.
- Focused orchestration and pilot validation slices are green.
- `automation/orchestration_v1` discovery, pilot flow/readiness, duplicate-candidate handling, end-to-end coverage, and recurring Copilot usage monitoring are implemented and regression-covered.
- All-repo readiness is green in the current environment when run under the documented contracts-only `MASTER_AGENT_REPO_CONFIGS` override.
- Exact-window trading pilot targeting and readiness are validated; `ready_to_send=true` is still the only green readiness state before live dispatch.
- In-repo blockers from the fresh validation pass: none.
- External environment blocker: live OpenAI-backed prompt refresh is still blocked in this environment by `401 invalid_api_key`.

Use `HANDOVER.md` and `docs/Todo.md` for the active backlog and blocker summary. Use the prompts below to drive workstreams against that current state.

---

## 1 — MASTER AUDIT PROMPT

_Paste this into a fresh Copilot agent chat in this repo to get a complete picture of the current state._

```
You are auditing the `desktop-agent-automation` repository. This system is designed to centrally manage multiple GitHub Copilot agents running in VS Code panels across one or more virtual desktops on Windows. Its north-star goal is: read TF/Contracts/Trading documents from a WSL trading-system repo via OpenAI API, derive prioritised workstreams, dispatch them into VS Code Copilot panels, collect outputs when finished, and automatically start new workstreams — all from one central loop.

Perform a full audit. For each section below, read the relevant files, run relevant tests, and produce a findings report.

### Section A — Architecture integrity
1. Read `docs/ARCHITECTURE.md` and `docs/ORCHESTRATION_V1_OPERATOR_RUNBOOK.md`.
2. Trace the end-to-end flow: `automation/orchestrator.py` (outer loop) → `automation/orchestration_v1/loop.py` (orchestration cycle) → `automation/orchestration_v1/vscode_pilot.py` (panel dispatch) → `automation/panel_seeding.py` (prompt injection) → `automation/master_prompt_orchestrator.py` (prompt generation from OpenAI).
3. Identify every broken seam — places where two modules must hand off data but no code path connects them.
4. List any module that is imported but never called from the runtime path.

### Section B — Work-item discovery gap
1. Read `automation/orchestration_v1/collector.py` and `automation/north_star.py`.
2. Determine what task sources are currently read (markdown files, agent_assignments.json, etc.) and what is missing.
3. Check whether `automation/cross_repo_todo_ingestion.py` output is consumed by the orchestration_v1 loop or only by the task discovery daemon.
4. Report the exact code gap that would need to be filled so that TF/Contracts/Trading `agent_assignments.json` tasks become the primary work queue for the orchestration loop.

### Section C — Panel lifecycle completeness
1. Read `automation/panel_tracker.py`, `automation/panel_followups.py`, `automation/panel_seeding.py`, and `automation/panel_task_dispatcher.py`.
2. Map: finished panel detected → output read → classification → new prompt chosen → new chat opened → prompt injected.
3. Find any step in that chain that is not executed automatically in the current runtime.
4. Check `automation/new_chat_prompt_tester.py` — is `_find_new_chat_button` wired into the seeding path?

### Section D — OpenAI integration depth
1. Read `automation/master_prompt_orchestrator.py` lines 800–1200 (the `refresh_all_feeds` implementation).
2. Confirm which docs paths are being read (DEFAULT_DOCS_ROOT, WSL path).
3. Confirm whether TF, contracts, and Trading are all included in the repo configs or only Trading.
4. Check `automation/north_star.py` REPO_ALIGNMENT_DOCS — are all three repos present?
5. Verify the OpenAI model being used and confirm it is appropriate for long-document ingestion.

### Section E — Tests and coverage
1. Run `python -m pytest tests/ -q --tb=short` and report pass/fail counts.
2. Identify any test that is currently marked `skip` or `xfail` that relates to the core runtime path.
3. Check whether an end-to-end integration test exists that exercises: orchestration_v1 loop → vscode_pilot dispatch → panel seeding with a live mock panel.

### Section F — Remaining backlog synthesis
1. Read `docs/Todo.md` and `HANDOVER.md`.
2. Cross-reference the open backlog items against the code gaps you found in sections A–E.
3. Produce a final prioritised list of the 10 most impactful remaining tasks, each with:
   - Description
   - Which files to modify
   - Estimated lines of new code
   - Blocking status (does anything else need to land first?)

Return the full audit report as structured markdown.
```

---

## 2 — WORKSTREAM PROMPTS

Each prompt below is a self-contained workstream for a single long-running agent session. They are ordered by impact toward the north-star goal.

---

### WS-1: Harden Orchestration V1 Work-Item Discovery

**Goal:** Replace markdown-bullet-only work discovery in `orchestration_v1/collector.py` with a rich multi-source ingestion pipeline that consumes `agent_assignments.json`, cross-repo TODO snapshots, and structured handover docs from all three trading-system repos (TF, contracts, Trading).

```
You are working in the `desktop-agent-automation` repository. Your goal is to produce a complete, tested, production-ready upgrade to the orchestration_v1 work-item discovery pipeline.

## Context
The orchestration_v1 loop (`automation/orchestration_v1/loop.py`) dispatches work items to VS Code Copilot panels. Work items are discovered by `automation/orchestration_v1/collector.py`. Currently the collector only parses markdown bullet lists, which means structured tasks in `agent_assignments.json`, cross-repo TODO snapshots from `automation/cross_repo_todo_ingestion.py`, and North Star priority context from `automation/north_star.py` are all ignored during discovery.

## What you must build

### Phase 1 — Multi-source ingestor (use sub-agents for parallel reads)
Spawn sub-agents to simultaneously read:
- `automation/orchestration_v1/collector.py` (current implementation, understand it fully)
- `automation/orchestration_v1/models.py` (WorkItem dataclass shape)
- `automation/cross_repo_todo_ingestion.py` (CrossRepoDependencyAnalysis, TodoItem)
- `automation/north_star.py` (ActiveTask, NorthStarContext, REPO_ASSIGNMENT_LEDGERS)
- `automation/orchestration_v1/loop.py` `run_once()` (how work items flow into decisions)

Then have each sub-agent return answers to:
1. What fields does WorkItem require? Can it be extended without breaking existing tests?
2. What does CrossRepoDependencyAnalysis.iter_critical_path() return and how does it map to a WorkItem?
3. What is the shape of ActiveTask and how does its `priority` field map to WorkCategory and Severity?
4. What diagnostics does the loop emit when no eligible work items are found? Where should richer source-mismatch errors go?

### Phase 2 — Implementation
1. Add a `from_agent_assignment(task: ActiveTask, repo_id: str) -> WorkItem` class-method or factory function in `automation/orchestration_v1/collector.py`.
2. Add a `from_todo_item(todo: TodoItem, repo_id: str) -> WorkItem` factory.
3. Extend `collect_repo_context()` to:
   a. Load the repo's `agent_assignments.json` via `north_star.REPO_ASSIGNMENT_LEDGERS[repo_id]` if present.
   b. Call `get_cross_repo_todo_service().get_analysis()` and filter items for this repo.
   c. Convert both sources to WorkItems using the new factories.
   d. Merge with markdown-extracted items, deduplicating by title hash.
4. Add diagnostic logging (at WARNING level) when a repo's task sources are missing or empty.
5. Update `normalize_work_items()` to accept items from any source, not just markdown.

### Phase 3 — Tests
Write tests in `tests/test_orchestration_v1_collector_enriched.py` covering:
- `from_agent_assignment` maps priority P0→BLOCKER, P1→HIGH, P2→MEDIUM correctly
- `from_todo_item` handles blocked items
- `collect_repo_context` falls back gracefully when `agent_assignments.json` is absent
- When an in_progress task exists in assignments, it is included with status RUNNING

### Phase 4 — Diagnostics improvement
In `automation/orchestration_v1/loop.py` `run_once()`, replace the generic "no eligible work items" stop message with a detailed `discovery_diagnostics` block that enumerates: which sources were checked, how many items each source provided, and why each candidate was rejected (allowlist, blocked term, dependency).

Run `python -m pytest tests/test_orchestration_v1_collector_enriched.py tests/test_orchestration_v1_golden_path.py tests/test_orchestration_v1_pilot_flow.py -v` and fix all failures before declaring done.

Return a final summary: which files were modified, how many new test cases were added, and a sample work item extracted from a real assignment file (use the fixture if the live WSL path is unavailable).
```

---

### WS-2: Wire End-to-End Feedback Seam — Panel Finish → New Workstream

**Goal:** Close the most important open integration gap: when a VS Code Copilot panel finishes, the output must be read, classified, fed back into the `MasterPromptOrchestrator`, and a new prompt seeded into a fresh chat — all without human intervention.

```
You are working in the `desktop-agent-automation` repository. Your goal is to close the end-to-end automation seam so that a finished panel automatically triggers a new workstream.

## Context
The individual components exist:
- `automation/panel_followups.py` — detects "task completed" / "next steps" in panel output
- `automation/panel_seeding.py` — can open a new chat and inject a prompt
- `automation/panel_task_dispatcher.py` — manages the task feed queue
- `automation/master_prompt_orchestrator.py` — reads trading-system docs and generates new prompts via OpenAI
- `automation/task_discovery_daemon.py` — background thread that refills the feed when it runs low

The gap: `panel_followups.py` handles a finished panel but does NOT call `task_discovery_daemon` or trigger `refresh_all_feeds()` when the queue is empty. The seeding path in `panel_seeding.py` does NOT fall back to on-demand orchestrator invocation when no pre-generated prompt is available.

## What you must build

Use sub-agents to read the following files in parallel before writing any code:
- Sub-agent A: Read `automation/panel_followups.py` (full file) and `automation/panel_seeding.py` (full file). Report: where does seeding fail silently when no prompt is available?
- Sub-agent B: Read `automation/task_discovery_daemon.py` (full file) and `automation/master_prompt_orchestrator.py` lines 1000–1150 (refresh_all_feeds core). Report: what triggers a daemon refresh cycle and what is the return value?
- Sub-agent C: Read `automation/panel_task_dispatcher.py` lines 1–120 (feed cache) and `automation/config.py` grep for FINISHED_PANEL*. Report: what happens when `next_entry()` finds no entries in the cache?

After sub-agents return:

### Implementation

1. **`automation/panel_task_dispatcher.py`**: Add a `register_feed_empty_callback(callback: Callable[[], None])` method to `TaskPanelDispatcher`. When `next_entry()` returns None and the cache is empty for all repos, fire the callback (if registered) in a non-blocking thread.

2. **`automation/task_discovery_daemon.py`**: Add a `trigger_immediate_refresh()` method that sets a flag causing the next loop iteration to skip its sleep and run immediately. Wire this as the callback registered in step 1.

3. **`automation/panel_seeding.py`**: In the function that handles a finished panel (trace from `handle_finished_panel` or equivalent), after the prompt send attempt, if no prompt was available and ENABLE_NEW_CHAT_RETRY is True, call `task_discovery_daemon.trigger_immediate_refresh()` and emit a structured log line: `[SEEDING] feed empty — triggered immediate refresh`.

4. **`automation/orchestrator.py`**: Ensure `TaskDiscoveryDaemon` is started as part of the main run loop setup (search for where it is or isn't instantiated and fix the gap).

5. **Config**: Add `ENABLE_ON_DEMAND_FEED_REFRESH = os.environ.get("ENABLE_ON_DEMAND_FEED_REFRESH", "true").lower() == "true"` in `automation/config.py` and gate the callback registration behind this flag.

### Tests

In `tests/test_feedback_seam_integration.py`:
- Test that when dispatcher has no entries, the empty callback is fired
- Test that `trigger_immediate_refresh()` causes the daemon to skip sleep and call refresh
- Test that the full chain (mock finished panel → no prompt → callback → mock refresh → new prompt available → seeded) works end-to-end with mocked orchestrator and mocked panel
- All tests must be pure unit/integration tests with no live UI dependencies

Run the full orchestration test suite: `python -m pytest tests/test_orchestration_v1_golden_path.py tests/test_orchestration_v1_pilot_flow.py tests/test_feedback_seam_integration.py -v`

Declare done only when all tests pass and the log line `[SEEDING] feed empty — triggered immediate refresh` is emitted in the appropriate test scenario.
```

---

### WS-3: Wire Copilot Usage Monitor Into Runtime

**Goal:** The `copilot_usage_monitor.py` module and its tests exist but the monitor never runs during the live automation session. Wire it into the main run loop as a recurring async poller.

```
You are working in the `desktop-agent-automation` repository. Your task is to wire the Copilot usage monitor into the live runtime loop so it runs automatically.

## Context
`automation/copilot_usage_monitor.py` tracks Copilot API usage metrics. Tests in `tests/test_copilot_usage_monitor.py` pass. However, the monitor is never instantiated or started in `automation/orchestrator.py` or `master.py`. The `P1 - Runtime Follow-Through` backlog item in `docs/Todo.md` tracks this gap explicitly.

## What you must build

### Phase 1 — Understand the module
Spawn a sub-agent to read `automation/copilot_usage_monitor.py` in full and answer:
1. What public API does it expose (class name, `start()`, `stop()`, interval)?
2. Does it already have a background thread or does it expect to be called in a loop?
3. What metrics does it emit and where (stdout, log file, metrics tracker)?
4. Does it depend on any live network calls or just local state?

### Phase 2 — Integration
1. In `automation/orchestrator.py`, find the section where the run loop initialises its components (near `TaskDiscoveryDaemon` or cost tracker). Add startup and shutdown of `CopilotUsageMonitor` here.
2. Ensure `stop()` is called on clean shutdown (KeyboardInterrupt / SIGTERM path).
3. In `automation/config.py`, add `ENABLE_COPILOT_USAGE_MONITOR = os.environ.get("ENABLE_COPILOT_USAGE_MONITOR", "true").lower() == "true"` and gate the startup behind it.
4. Emit a log line at startup: `[USAGE_MONITOR] Copilot usage monitor started (interval={interval}s)`.

### Phase 3 — Rate monitor alignment
Read `automation/rate_monitor.py`. If the Copilot usage monitor and the rate monitor track overlapping metrics, document the difference in `docs/METRICS.md` under a new "Runtime Monitors" section, and avoid double-counting in any dashboard output.

### Phase 4 — Tests
In `tests/test_copilot_usage_monitor_integration.py`:
- Test that when `ENABLE_COPILOT_USAGE_MONITOR=true` the monitor is started during run loop init
- Test that the monitor emits its periodic check even when no Copilot activity occurs
- Test graceful stop on shutdown

Run `python -m pytest tests/test_copilot_usage_monitor.py tests/test_copilot_usage_monitor_integration.py -v` and fix all failures.
```

---

### WS-4: Harden WSL ↔ Windows Path Boundary for Trading-System Docs

**Goal:** The orchestrator reads trading-system docs from a WSL path (`\\wsl.localhost\Ubuntu-24.04\...`). This path can fail silently when WSL is slow, offline, or the distro name differs. Add resilient path resolution, health checks, and a fallback.

```
You are working in the `desktop-agent-automation` repository. Your task is to make the WSL document-reading path resilient so the orchestrator never silently generates empty prompts due to WSL being unavailable.

## Context
`automation/master_prompt_orchestrator.py` defaults to `DEFAULT_DOCS_ROOT = \\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\tf_1\docs`.
`automation/north_star.py` has `_WSL_BASE = \\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system`.
When WSL is not responding, `Path.exists()` on these UNC paths hangs or returns False with no diagnostic output, causing the orchestrator to generate empty prompt batches silently.

## What you must build

Use sub-agents to read in parallel:
- Sub-agent A: Read `automation/master_prompt_orchestrator.py` lines 80–200 (path resolution, `_find_repo_docs_by_name`) — report every place a WSL path is accessed without a timeout or existence check
- Sub-agent B: Read `automation/north_star.py` lines 1–120 — report every WSL path access, timeouts, and whether `get_north_star()` can be called safely offline

### Implementation

1. **`automation/utils.py`** (or create `automation/wsl_paths.py`): Add `probe_wsl_path(path: Path, timeout_seconds: float = 3.0) -> bool`. This function checks if a UNC WSL path is reachable within a timeout using `concurrent.futures.ThreadPoolExecutor` to run `path.exists()` with a timeout. Returns True if reachable, False otherwise.

2. **`automation/master_prompt_orchestrator.py`**: Before collecting docs from any WSL path, call `probe_wsl_path()`. If it returns False:
   - Emit `[ORCHESTRATOR] WSL path unreachable: {path} — falling back to cached docs` at WARNING level
   - Check for a local fallback cache: `state/docs_cache/{repo_name}/` (a directory of last-known-good doc snapshots)
   - If cache exists, use it. If not, skip this repo and log at ERROR level.

3. **`automation/north_star.py`**: Wrap the WSL path reads in `get_north_star()` with the same `probe_wsl_path()` guard. If WSL is unavailable, return a `NorthStarContext` built from a cached snapshot in `state/north_star_cache.json` (update this cache every successful read).

4. **Cache write**: After every successful WSL doc read in the orchestrator, write snapshots to `state/docs_cache/{repo_name}/`. After every successful north_star load, write `state/north_star_cache.json`.

5. **`automation/config.py`**: Add:
   - `WSL_PATH_PROBE_TIMEOUT_SECONDS = float(os.environ.get("WSL_PATH_PROBE_TIMEOUT_SECONDS", "3.0"))`
   - `ENABLE_WSL_DOC_CACHE = os.environ.get("ENABLE_WSL_DOC_CACHE", "true").lower() == "true"`

### Tests
In `tests/test_wsl_path_resilience.py`:
- Test `probe_wsl_path` returns False for a nonexistent UNC path without hanging
- Test orchestrator falls back to cache when WSL probe fails
- Test north_star returns cached context when WSL probe fails
- Test cache is written after a successful read (use a temp directory)

Run `python -m pytest tests/test_wsl_path_resilience.py -v` and fix all failures.
```

---

### WS-5: Orchestration V1 — End-to-End Integration Test Suite

**Goal:** Prove the full end-to-end orchestration cycle works: registry load → work item discovery → dispatch to a mock VS Code panel → mock panel completes → worker report parsed → ledger updated.

```
You are working in the `desktop-agent-automation` repository. Your task is to write a comprehensive end-to-end integration test suite for the orchestration_v1 system that covers the full dispatch-complete-report cycle without requiring a live VS Code window.

## Context
Existing tests:
- `tests/test_orchestration_v1_golden_path.py` — covers the loop's selection logic
- `tests/test_orchestration_v1_pilot_flow.py` — covers vscode_pilot dispatch logic
- `tests/test_orchestration_v1_cli_readiness.py` — covers CLI entry point

Gap: no test exercises the complete cycle from `run_once()` detecting a work item through to receiving and processing a structured worker completion report and updating the ledger.

## What you must build

Spawn sub-agents to read in parallel before writing any code:
- Sub-agent A: Read `automation/orchestration_v1/loop.py` lines 80–200 (`run_once()` body) — map every external call that needs to be mocked
- Sub-agent B: Read `automation/orchestration_v1/worker_protocol.py` — understand the full START/END marker protocol and what a valid completion JSON looks like
- Sub-agent C: Read `automation/orchestration_v1/ledger.py` — understand how the ledger records dispatched and completed work items
- Sub-agent D: Read `tests/fixtures/` contents and `tests/test_orchestration_v1_golden_path.py` — understand existing fixture patterns

After sub-agents return, write `tests/test_orchestration_v1_e2e.py` covering:

1. **Happy path**:
   - Load fixture registry with one repo and one high-priority work item
   - Mock `vscode_pilot.dispatch_to_panel()` to return a mock panel handle
   - Mock panel output to return a valid START/END marker worker report
   - Mock ledger write
   - Run `loop.run_once()`
   - Assert: work item was selected, dispatch was called, ledger shows status=COMPLETED, OrchestrationCycleResult has outcome=SUCCESS

2. **Worker report parse failure**:
   - Mock panel output returns malformed response (no markers)
   - Assert: ledger shows status=FAILED, loop emits E_MARKER_START_INVALID diagnostic
   - Assert: next `run_once()` selects a new work item (failed item is not re-selected indefinitely)

3. **No eligible work items (full diagnostics)**:
   - Registry with one repo where all items are blocked
   - Assert: OrchestrationCycleResult has action="stop" and diagnostics.stop_reason is a non-empty string explaining why

4. **Allowlist gating**:
   - Registry with pilot_allowlist_enabled=True
   - Work item whose title contains a blocked term
   - Assert: item is rejected with blocked_term_counts > 0

5. **Multi-repo prioritisation**:
   - Registry with two repos, each having one work item
   - contracts item has BLOCKER severity, Trading item has HIGH
   - Assert: contracts item is selected first (respects REPO_DEPENDENCY_ORDER)

Run `python -m pytest tests/test_orchestration_v1_e2e.py -v` with no live UI dependencies. All assertions must be deterministic. Add the new test file to `pyproject.toml` under the `orchestration` marker.
```

---

### WS-6: Priority Dashboard — Central Agent Management UI

**Goal:** Build a terminal dashboard that shows, in real time, the state of every managed agent (which repo, what task, how long running, last output preview, queue depth) so you can see the full agent estate at a glance from one terminal.

```
You are working in the `desktop-agent-automation` repository. Your task is to build a live terminal dashboard that gives a single-pane view of all managed agents and their current workstreams.

## Context
Individual status outputs exist:
- `scripts/panel_quality_dashboard.py` — per-panel quality scores
- `automation/metrics.py` — prompt seeding and success rate metrics
- `automation/cost_tracker.py` — OpenAI API cost per repo/model
- `automation/orchestration_v1/ledger.py` — dispatch and completion history
- `automation/panel_state.json` — live panel states

No tool combines all of these into a single live view.

## What you must build

Use sub-agents to read in parallel:
- Sub-agent A: Read `automation/panel_state.py` and `automation/panel_state.json` (schema) — what fields exist per panel?
- Sub-agent B: Read `automation/metrics.py` and `automation/cost_tracker.py` — what summary methods are available?
- Sub-agent C: Read `automation/orchestration_v1/ledger.py` — what is the data model and how to query last N events?
- Sub-agent D: Read `scripts/panel_quality_dashboard.py` — what is the rendering pattern? Can it be extended?

Then build `scripts/agent_dashboard.py`:

### Dashboard layout (terminal, rich library or plain ANSI)

```

╔══════════════════════════════════════════════════════╗
║ AGENT ESTATE DASHBOARD — 2026-04-25 14:32:07 ║
╠══════════╦══════════════╦══════════╦══════════════════╣
║ Panel ║ Repo ║ Status ║ Task (preview) ║
╠══════════╬══════════════╬══════════╬══════════════════╣
║ Panel 1 ║ Trading ║ RUNNING ║ Implement… ║
║ Panel 2 ║ TF ║ FINISHED ║ Add tests… ║
║ Panel 3 ║ contracts ║ IDLE ║ — ║
╠══════════╩══════════════╩══════════╩══════════════════╣
║ QUEUE Trading:3 TF:1 contracts:0 ║
║ COST Session: $0.42 Total: $12.31 ║
║ RATE Allows/hr: 14 Allows/30min: 6 ║
╚══════════════════════════════════════════════════════╝

````

### Requirements
1. `--watch` mode: refresh every 5 seconds (default), configurable via `--interval`
2. `--json` mode: emit the dashboard data as JSON for piping to other tools
3. `--repo <name>` filter: show only panels for a specific repo
4. Colour-code status: RUNNING=green, FINISHED=yellow, IDLE=grey, BLOCKED=red
5. Show last orchestration_v1 ledger event (timestamp + outcome) in a footer line
6. Include queue depth per repo (from `TaskPanelDispatcher` feed cache)
7. Include session cost (from cost tracker) and allow-click rate (from metrics)

### CLI registration
Add the dashboard to `automation/cli/master.py` under key `agent-dashboard`:
```python
"agent-dashboard": WorkflowDef(
    key="agent-dashboard",
    description="Live terminal dashboard for all managed agents",
    args=("-m", "scripts.agent_dashboard"),
)
````

So it can be invoked as `master --run agent-dashboard`.

### Tests

In `tests/test_agent_dashboard.py`:

- Test `--json` mode produces valid JSON with keys: panels, queue_depths, session_cost, allow_rate
- Test `--repo Trading` filters to only Trading panels
- Test gracefully handles missing `panel_state.json`

Run `python -m pytest tests/test_agent_dashboard.py -v`.

```

---

### WS-7: OpenAI Doc-Ingestion Pipeline — Full Trading-System Coverage

**Goal:** Ensure all three trading-system repos (TF, contracts, Trading) are included in every `refresh_all_feeds()` call, with per-repo prompt specialisation matching each repo's role.

```

You are working in the `desktop-agent-automation` repository. Your task is to ensure the OpenAI-powered prompt generation pipeline covers all three trading-system repositories with prompts tailored to each repo's role.

## Context

`automation/master_prompt_orchestrator.py` has `DEFAULT_DOCS_ROOT` pointing only to `tf_1/docs`.
`automation/north_star.py` defines all three repos: TF, contracts, Trading — each with distinct docs paths and role boundaries.
`MASTER_AGENT_REPO_CONFIGS` in `automation/config.py` may only include one repo if not explicitly configured.

The goal: every refresh cycle should read docs from all three repos, understand the dependency order (contracts → TF → Trading), and generate prompts that respect repo boundaries and the North Star goal.

## What you must build

Spawn sub-agents to read in parallel:

- Sub-agent A: Read `automation/config.py` grep `MASTER_AGENT_REPO_CONFIGS` — what is its current shape and default value?
- Sub-agent B: Read `automation/master_prompt_orchestrator.py` lines 800–1050 (`refresh_all_feeds`) — how does it iterate repos and does it use north_star context?
- Sub-agent C: Read `automation/north_star.py` `NorthStarContext` class and `REPO_ALIGNMENT_DOCS` — what per-repo documents contain role/boundary information?
- Sub-agent D: Read `docs/MULTI_REPO_GUIDE.md` — what is the documented intended multi-repo configuration?

After sub-agents return:

### Implementation

1. **`automation/config.py`**: Update `MASTER_AGENT_REPO_CONFIGS` default to include all three repos:

```python
MASTER_AGENT_REPO_CONFIGS = json.loads(os.environ.get("MASTER_AGENT_REPO_CONFIGS", json.dumps([
    {"name": "contracts", "docs_dirs": [str(CONTRACTS_REPO_ROOT / "docs")], "role": "contract definitions source of truth"},
    {"name": "TF",        "docs_dirs": [str(TF_REPO_ROOT / "docs")],       "role": "trading framework, upstream of Trading"},
    {"name": "Trading",   "docs_dirs": [str(TRADING_REPO_ROOT / "docs")],  "role": "live trading system, downstream consumer"},
])))
```

(Import the path constants from north_star or replicate them with env-var overrides.)

1. **`automation/master_prompt_orchestrator.py`**: In `_build_system_prompt()` (or equivalent), inject the repo's `role` string and the current North Star P0/P1 tasks for that repo into the system prompt so GPT generates prompts that are role-aware and not just generically helpful.

2. **`automation/master_prompt_orchestrator.py`**: Respect `REPO_DEPENDENCY_ORDER` (contracts → TF → Trading) when iterating repos so that contracts prompts are generated before TF, which are generated before Trading. This ensures trading-system agents work in the right dependency order.

3. **`automation/master_prompt_orchestrator.py`**: Add a `generate_cross_repo_coordination_prompt()` method that generates one special prompt per cycle summarising the current in-flight tasks across all repos (from `get_north_star()`) and suggesting the next highest-leverage cross-repo action. Write this to `tasks/generated_prompts/cross_repo_coordination.md`.

4. **Docs**: Update `docs/MULTI_REPO_GUIDE.md` with a new section "Production Configuration" showing how to set `MASTER_AGENT_REPO_CONFIGS` and the expected output structure.

### Tests

Update `tests/test_master_prompt_orchestrator.py` and `tests/test_master_prompt_orchestrator_enhanced.py`:

- Test that `refresh_all_feeds()` with default config calls `_process_repo()` for all three repos
- Test that role and north_star context appear in the generated system prompt
- Test that repos are processed in dependency order
- Test `generate_cross_repo_coordination_prompt()` produces a non-empty string when north_star has ≥1 active task

Run `python -m pytest tests/test_master_prompt_orchestrator.py tests/test_master_prompt_orchestrator_enhanced.py -v`.

```

---

## 3 — HOW TO USE THESE PROMPTS

**Recommended execution order** (each workstream unblocks the next):

```

WS-4 (WSL resilience) ← unblocks everything that reads WSL
↓
WS-1 (work discovery) ← richer task queue
↓
WS-7 (3-repo ingestion) ← all repos feed the queue
↓
WS-2 (feedback seam) ← panels auto-requeue
↓
WS-3 (usage monitor) ← observability
↓
WS-5 (E2E tests) ← confidence net
↓
WS-6 (dashboard) ← operator visibility

```

**Parallelisation**: WS-3, WS-5, and WS-6 have no dependencies on each other and can run in parallel agent sessions.

**For long-running agents**: Each WS prompt above is scoped to 2–5 hours of agent work. Structure your VS Code panels so each workstream gets its own Copilot panel in the relevant repo. The orchestrator will handle re-queuing automatically once WS-2 is complete.

---

## 4 — ESTIMATED TIME TO NORTH-STAR GOAL

Given the current ~70% readiness:

| Workstream | Effort | Impact on north-star |
|---|---|---|
| WS-4 WSL resilience | 1–2 agent sessions | Unblocks live doc reading |
| WS-1 Work discovery | 2–3 agent sessions | Closes biggest logic gap |
| WS-7 3-repo ingestion | 1–2 agent sessions | Full trading-system coverage |
| WS-2 Feedback seam | 2–3 agent sessions | Self-managing loop closes |
| WS-3 Usage monitor | 1 agent session | Observability |
| WS-5 E2E tests | 2 agent sessions | Confidence |
| WS-6 Dashboard | 1–2 agent sessions | Operator UX |

After WS-1 through WS-2 land, the core loop will be self-managing. WS-4 through WS-7 harden it toward the production target. The system will be fully operational as described (reading TF/Contracts/Trading → deriving priorities → dispatching to panels → collecting results → self-requeuing) once WS-1, WS-2, WS-4, and WS-7 are all merged.
```
