# Panel Lifecycle and State Machine

This guide documents how Copilot panels are tracked over time, how state transitions are applied, and how seeding, error recovery, and cleanup work.

## 1. Core Concepts

### 1.1 PanelState

`automation.panel_state.PanelState` represents a single tracked panel and includes:

- Identity: `window_title`, `panel_id`, `repo_name`.
- Timing: `first_seen`, `last_allow_click`, `last_output_change`, `last_scanned`, `last_allow_check`.
- Output sampling: `last_output_sample`, `last_output_hash`.
- Status flags:
  - `status`: enum `PanelStatus`.
  - `is_running`: whether the agent appears to be actively generating output.
  - `idle_reason`: enum `IdleReason` (e.g., `WAITING_ALLOW`, `POSSIBLY_FINISHED`, `RATE_LIMITED_BUTTON`).
- Classification: last response category, confidence, evidence, secondary categories.
- Assignment metadata: prompt/task IDs, source, batch ID.
- Transcript snapshots: compact history of prompts and completions.

### 1.2 PanelStatus values

From `automation.panel_state.PanelStatus`:

- `RUNNING`: Copilot is generating output.
- `WAITING_ALLOW`: Allow permission required.
- `RATE_LIMITED`: Rate limit detected.
- `IDLE`: No active generation; waiting for input.
- `FINISHED`: Output is stable; potentially ready for follow-ups.
- `COMPLETED`: Work is fully done (per parser semantics).
- `STALE`: Panel has not been scanned recently (desktop may be unreachable).
- `NEEDS_INPUT`: Copilot is asking for clarification from the user.
- `ERROR`: Copilot reported an error.

---

## 2. Lifecycle and State Transitions

### 2.1 Timeline overview

A typical panel goes through these high-level phases:

1. **Activation**
   - User or automation clicks **Allow**.
   - `PanelTracker.record_allow_click`:
     - Creates or updates a `PanelState`.
     - Sets `status = RUNNING`, `is_running = True`.
     - Records `first_seen`, `last_allow_click`, `repo_name`.

2. **Active generation**
   - `update_panel_output(window_title, output_text, is_running=True, panel_id=...)`:
     - Updates `last_output_sample` and `last_output_hash`.
     - Re-classifies the last output via `classify_response`.
     - Records response feedback metrics.
     - Adjusts status based on response category.

3. **Idle vs Finished**
   - `update_panel_status()` periodically evaluates all panels using time thresholds:
     - After `PANEL_IDLE_THRESHOLD_MINUTES` with no Allow clicks, `RUNNING → IDLE`.
     - After `PANEL_FINISHED_THRESHOLD_MINUTES` with no output changes while `IDLE`, `IDLE → FINISHED`.

4. **Follow-ups & seeding**
   - `PanelTracker.get_finished_panels_needing_attention()` identifies finished panels needing responses or completion checks.
   - `panel_seeding.process_finished_panels_with_prompts`:
     - Uses per-repo prompt feeds to seed new work into finished panels.

5. **Completion or Error**
   - When the response parser detects completion, clarification, or error:
     - `_apply_response_category` transitions status to `COMPLETED`, `NEEDS_INPUT`, or `ERROR` and sets `idle_reason` accordingly.

6. **Staleness and cleanup**
   - `update_panel_status()` marks panels as `STALE` if `last_scanned` is older than `PANEL_STALE_THRESHOLD_MINUTES`.
   - Stale panels may be ignored for follow-ups and eventually removed when `panel_state.json` is reset or pruned.

### 2.2 State transition rules (simplified)

- On Allow click:
  - Any state → `RUNNING`, `is_running = True`.
- On new output while `STALE`:
  - `STALE` → `RUNNING` (if `is_running=True`) or `IDLE` (if `is_running=False`).
- On classifier result:
  - `COMPLETED` response → `status = COMPLETED`, `idle_reason = None`.
  - `ASKING_CLARIFICATION` → `status = NEEDS_INPUT`, `idle_reason = AWAITING_USER`.
  - `ERROR` → `status = ERROR`, `idle_reason = None`.
  - `SUGGESTING_NEXT_STEPS` → `status = FINISHED`, `idle_reason = POSSIBLY_FINISHED`.
  - If previously `NEEDS_INPUT` or `ERROR` and new non-special output appears → `RUNNING` or `IDLE` depending on `is_running`.
- On time-based checks (`update_panel_status`):
  - Long time since last scan → `STALE`.
  - Long time since last Allow click while running → `RUNNING → IDLE`.
  - Long time since last output change while idle → `IDLE → FINISHED`.

---

## 3. Seeding Workflows

### 3.1 Finished-panel follow-ups

`automation.panel_seeding.process_finished_panels_with_prompts`:

1. Refresh panel states:
   - `tracker.update_panel_status()`.
   - `finished_panels = tracker.get_finished_panels()` (or a helper filtering FINISHED panels).
2. Sync assignments:
   - `dispatcher = get_task_panel_dispatcher()`.
   - `dispatcher.sync_active_assignments(tracker)`.
   - `dispatcher.track_idle_panels([...])` for eligible finished panels.
3. For each finished panel:
   - Ensure window focus via `_ensure_panel_window_focus`.
   - Optionally click **Keep edits** and associated dialogs.
   - Open **New Chat** using `_open_new_chat`.
   - Select model using `_detect_model_label` and `_select_model`.
   - Send prompt text using `panel_ui.send_text_to_chat`.
   - Record seeding and assignment metrics.
   - Mark `panel.seeded_prompt = True` to avoid reseeding.

### 3.2 Prompt sources

- Primary source: task feeds managed by `panel_task_dispatcher`, with per-repo queues.
- Fallback: legacy round-robin prompt blocks loaded via `_load_prompt_blocks_for_repo(repo_name)` when no feed entries exist for a repo.

### 3.3 Failure handling during seeding

- If window focus cannot be obtained, the panel is skipped for this cycle.
- If **New Chat** or model picker selectors fail due to UI changes, metrics will record failures with descriptive messages.
- If sending text fails, the panel remains `FINISHED` but `seeded_prompt` is not set, so it may be retried later after a fix.

---

## 4. Error Recovery Paths

### 4.1 Panel needs input (`NEEDS_INPUT`)

- Triggered when the response parser classifies output as clarification.
- Automation should **not** auto-respond; user input is expected.
- Recovery:
  - User provides clarification in the Copilot chat.
  - On new output, if classification no longer indicates clarification or error, status returns to `RUNNING` or `IDLE`.

### 4.2 Panel error (`ERROR`)

- Triggered on explicit Copilot error messages.
- Recovery:
  - User or supervising agent may retry or adjust the request.
  - On the next successful output, `_apply_response_category` clears the error state.

### 4.3 Stale panels (`STALE`)

- Typically caused by unreachable desktops, closed windows, or long periods without scanning.
- Recovery strategies:
  - Fix desktop switching issues and let `update_panel_output` run once; stale panels will be reclassified to `RUNNING` or `IDLE` as soon as fresh output or scans occur.
  - If windows were closed, delete `automation/panel_state.json` or prune stale entries to remove dead panels.

---

## 5. Health Monitoring

### 5.1 Panel counts and status distribution

Use the `PanelTracker` directly to inspect health:

```powershell
python - << 'EOF'
from automation.panel_tracker_core import PanelTracker

tracker = PanelTracker()
status_counts = {}
for panel in tracker.panels.values():
    status_counts[panel.status.value] = status_counts.get(panel.status.value, 0) + 1

print("Panel status counts:", status_counts)
EOF
```

- Watch for large numbers of `STALE`, `ERROR`, or `NEEDS_INPUT` panels.

### 5.2 Transcript snapshots and sensitivity

- `PanelTracker` records compact transcript snapshots using `TranscriptSnapshot` with:
  - Content hashes.
  - Optional previews (masked if content appears sensitive).
- This enables monitoring of:
  - How often panels complete.
  - How long outputs are, without storing raw content.

---

## 6. Cleanup Procedures

### 6.1 Full reset

Safe when you want to discard all historical panel tracking:

```powershell
Stop-Process -Name python -ErrorAction SilentlyContinue  # stop automation
Remove-Item automation\panel_state.json -ErrorAction SilentlyContinue
```

- On the next run, `PanelTracker` will start with an empty state.

### 6.2 Targeted pruning (advanced)

You can remove only specific panels:

```powershell
python - << 'EOF'
from automation.panel_tracker_core import PanelTracker

tracker = PanelTracker()

# Example: drop all STALE panels
keys_to_drop = [k for k, p in tracker.panels.items() if p.status.name == 'STALE']
for k in keys_to_drop:
    tracker.panels.pop(k, None)

# Force save
tracker._save_state()
print("Dropped", len(keys_to_drop), "stale panels")
EOF
```

- Always back up `automation/panel_state.json` before heavy edits.

---

## 7. Best Practices

- Keep VS Code windows visible and avoid long periods where desktops are unreachable.
- Tune timing thresholds (`PANEL_IDLE_THRESHOLD_MINUTES`, `PANEL_FINISHED_THRESHOLD_MINUTES`, `PANEL_STALE_THRESHOLD_MINUTES`) in `PanelTracker` if your workflows are unusually long or short.
- Use metrics (`automation/metrics.json`, `automation/assignment_metrics.jsonl`) alongside panel state to get a full picture of health and responsiveness.
