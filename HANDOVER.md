# Handover: Finished Panel Follow-Through Implementation

**Documentation Synced: December 11, 2025** - Todo.md updated with completed panel classification task and new roadmap items with dependencies. Operators should refer to docs/Todo.md for latest plan.

## What Was Built

Extended the desktop automation system to autonomously drive idle/finished Copilot agent panels through a complete workflow:
1. Detect when a panel is idle/finished (no Cancel button, no Allow button, output unchanged for 30+ minutes)
2. Click "Keep Edits" if present
3. Open "New Chat" 
4. Select the appropriate model (Grok, Codex Mini, Codex, Codex Max) based on prompt metadata
5. Paste the next prompt from `tasks/generated_prompts/latest.txt`
6. Mark the panel as seeded so it only happens once per finish cycle

## Key Files Modified

### `automation/master_prompt_orchestrator.py`
- **System prompt updated** to match your specification: up to 20 tasks, docs/Todo/assignments sweep, agent selection (Grok/Codex Mini/Codex/Codex Max), filing completed docs to `docs/completed`, no code fences in output
- **Workspace detection added** via `_detect_repo_doc_roots()`: prefers local `docs`/`docs/open_tasks` from current working directory, falls back to WSL UNC paths in env vars

### `automation/panel_tracker.py`
- **New flag**: `ENABLE_FINISHED_PANEL_FOLLOWUPS` (default: false) gates the entire finished-panel automation
- **New flag**: `FINISHED_PANEL_DRY_RUN` (default: false) logs actions instead of executing UI clicks/text for safe testing
- **Prompt loading**: `_load_prompt_blocks()` reads and splits `tasks/generated_prompts/latest.txt` into individual prompts
- **Model inference**: `_detect_model_label()` parses prompt header to pick Grok/Codex Mini/Codex/Codex Max
- **UI helpers**: `_find_new_chat_button()`, `_find_model_picker_button()`, `_select_model()`, `_open_new_chat()` drive the VS Code UI
- **Keep Edits click**: `_try_click_keep_edits()` reuses the existing button clicker
- **Main handler**: `process_finished_panels_with_prompts()` orchestrates the entire flow for each finished panel
- **State tracking**: Added `seeded_prompt` field to `PanelState` to ensure each finished panel only gets one new prompt

## Panel Transcript Snapshots (Dec 11, 2025)

- `automation/panel_tracker.py` now tracks compact `transcript_snapshots` (seed prompts plus the last completion hash/preview) on each `PanelState`. This keeps `panel_state.json` informative without storing full transcripts.
- Migration steps: no manual edits are required. Existing `panel_state.json` records load with empty `transcript_snapshots`, but you should let the tracker save the file once (run the orchestrator or delete `automation/panel_state.json` to rebuild) so future sessions persist the new field.
- Privacy guardrails remain enforced. If a completion looks sensitive, only the hash and a `<filtered>` marker are stored in the transcript snapshot.

### `automation/orchestrator.py`
- **Import added**: `from automation.panel_tracker import process_finished_panels_with_prompts`
- **Call added**: After each scan cycle (before sleep), invokes `process_finished_panels_with_prompts(vscode_windows)` to drive finished panels

### `automation/config.py`
- **`ENABLE_FINISHED_PANEL_FOLLOWUPS`**: Master toggle (default: false)
- **`FINISHED_PANEL_DRY_RUN`**: Dry-run mode (default: false) - logs only, no UI actions
- **`FINISHED_PANEL_PROMPT_PATH`**: Path to prompt batch file (default: `tasks/generated_prompts/latest.txt`)
- **`MODEL_PICKER_LABELS`**: Mapping of model keys to UI labels (e.g., `"codex-max"` → `"GPT-5.1-Codex-Max (Preview)"`)

### `tests/test_finished_panel_followups.py`
- Unit tests covering dry-run and live paths for the target panel "Testing window functionality - desktop-agent-automation"
- Mocks UI interactions, validates state transitions and seeding logic

## Configuration & Usage

### Environment Variables (PowerShell)
```powershell
# Enable finished-panel follow-through (required)
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"

# Enable text sending to panels (required, safety gate)
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# Dry-run mode (optional, recommended for first test)
$env:FINISHED_PANEL_DRY_RUN = "true"  # logs only, no clicks/paste

# Path to prompt batch (optional, defaults to tasks/generated_prompts/latest.txt)
$env:FINISHED_PANEL_PROMPT_PATH = "path\to\prompts.txt"
```

### Safe Testing Workflow

1. **Prepare test panel**:
   - Open VS Code with Copilot chat
   - Ensure panel title is `Testing window functionality - desktop-agent-automation`
   - Let the agent finish or manually stop it (no Cancel/Allow visible)
   - Make sure it's been idle for 30+ minutes or manually mark it as finished in `automation/panel_state.json`

2. **Ensure prompt file exists**:
   ```powershell
   # Create test prompt if needed
   Set-Content -Path "tasks/generated_prompts/latest.txt" -Value "Prompt 1 (Codex Max): Test prompt for verification"
   ```

3. **Run dry-run first**:
   ```powershell
   $env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
   $env:FINISHED_PANEL_DRY_RUN = "true"
   $env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"
   python -m automation.orchestrator
   ```
   - Watch console for `[PanelTracker][DRY-RUN] Would keep edits, open new chat, and send prompt to: Testing window functionality...`
   - No UI actions occur, only logging

4. **Run live (after dry-run validates)**:
   ```powershell
   $env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
   $env:FINISHED_PANEL_DRY_RUN = "false"  # or omit this line
   $env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"
   python -m automation.orchestrator
   ```
   - Watch the test panel: should see Keep Edits clicked, New Chat opened, model selected, prompt pasted
   - Press Ctrl+C to stop after verification

### Unit Tests
```powershell
python -m pytest tests/test_finished_panel_followups.py -v
```

## How It Works

### Flow
1. **Orchestrator main loop** runs every `MIN_SCAN_INTERVAL_SECONDS` (typically 5s)
2. **After button scanning**, calls `process_finished_panels_with_prompts(vscode_windows)`
3. **Panel tracker**:
   - Loads finished panels (status = FINISHED, idle 30+ min, output unchanged 30+ min)
   - Filters out panels already seeded (`seeded_prompt = True`)
   - Loads prompt blocks from `tasks/generated_prompts/latest.txt`
   - For each finished panel:
     - In **dry-run mode**: logs what would happen, marks as seeded
     - In **live mode**:
       - Clicks Keep Edits (if present)
       - Opens New Chat
       - Selects model based on prompt header (e.g., "Codex Max" → `GPT-5.1-Codex-Max (Preview)`)
       - Pastes prompt via `send_text_to_chat()` (clipboard method)
       - Marks panel as RUNNING, updates `last_allow_click`, sets `seeded_prompt = True`

### Safety Gates
- **Double flag requirement**: Both `ENABLE_FINISHED_PANEL_FOLLOWUPS` and `ENABLE_SEND_TO_INACTIVE_PANELS` must be true
- **User text detection**: `send_text_to_chat()` skips panels that already have text in the input box
- **Once-per-finish**: `seeded_prompt` flag prevents re-seeding the same finished panel
- **Dry-run mode**: Test without any UI interactions

### Model Selection
Prompt header is parsed for model hints:
- `"Grok"` → Grok
- `"Codex Mini"` or `"codex-mini"` → GPT-5.1 Codex Mini
- `"Codex Max"` or `"codex-max"` → GPT-5.1-Codex-Max (Preview)
- `"Codex"` (alone) → GPT-5.1 Codex

If no model detected, no model picker click occurs (uses panel's current default).

## Known Issues & Limitations

1. **No prompt rotation**: Always uses the first prompt from `latest.txt`. If you want round-robin, implement a prompt queue/index in `PanelState`.

2. **Model picker UI brittleness**: Relies on exact button name `"Pick Model (Ctrl+Alt+.)"` and menu item names like `"GPT-5.1-Codex-Max (Preview)"`. If VS Code UI changes, update `MODEL_PICKER_LABELS` in config.

3. **Window detection**: Only processes VS Code windows found by `find_all_vscode_windows()`. If the test panel is on a different desktop/minimized, it won't be detected.

4. **Panel state persistence**: `automation/panel_state.json` tracks all panels. To reset for testing, delete this file.

5. **Lint warnings**: Pre-existing type errors in `panel_tracker.py` for `GetTextPattern`/`GetValuePattern`/`SetActive` (uiautomation stubs incomplete) don't affect runtime.

6. **No repo-root detection for Windows vs WSL yet**: Workspace detection prefers local `docs` folder but doesn't switch between `C:\Users\...\docs` and `\\wsl.localhost\...\docs` based on active window. Current heuristic: uses CWD or env overrides.

## Next Steps & Enhancements

### Immediate
- [ ] Validate dry-run on real test panel ("Testing window functionality - desktop-agent-automation")
- [ ] Test live mode on same panel with a benign prompt
- [ ] Monitor logs for 5-10 minutes to ensure no false positives

### Short-term
- [ ] Implement prompt queue/round-robin instead of always first prompt
- [ ] Add repo-root detection from foreground VS Code window title (parse for repo name)
- [ ] Create `docs/Todo.md` stub in both repos (currently missing)
- [ ] Add metrics: track seeded prompts, model selections, success rates

### Medium-term
- [ ] API call to classify idle panel output as "next steps" vs "truly finished" before seeding
- [ ] Handle "OK" button after Keep Edits if agent wants confirmation
- [ ] Retry logic if New Chat fails to open or model picker not found
- [ ] Better error recovery: if seeding fails, mark panel as needing retry instead of seeded

### Advanced
- [ ] Multi-repo support: maintain separate prompt batches per repo
- [ ] Agent assignment tracking: which prompt was sent to which panel
- [ ] Feedback loop: parse agent response to auto-mark as completed or adjust next prompt
- [ ] Cost tracking: estimate OpenAI spend from seeded prompts + agent runs

## Testing Checklist

- [x] Unit tests pass (`pytest tests/test_finished_panel_followups.py`)
- [ ] Dry-run logs show correct panel detection
- [ ] Live mode clicks Keep Edits on test panel
- [ ] Live mode opens New Chat successfully
- [ ] Live mode selects correct model (verify in UI after paste)
- [ ] Live mode pastes prompt without errors
- [ ] Panel marked as seeded in `panel_state.json`
- [ ] No duplicate seeding on subsequent scans
- [ ] User-text detection prevents sends to panels with existing input

## Rollback Plan

If issues arise:
1. Set `ENABLE_FINISHED_PANEL_FOLLOWUPS=false` to disable entirely
2. Delete `automation/panel_state.json` to reset tracking
3. Revert changes to `orchestrator.py`, `panel_tracker.py`, `config.py` via git

## Documentation Updates Needed

- [ ] Update `README.md` with finished-panel follow-through section
- [ ] Add environment variable reference table
- [ ] Document model picker UI dependencies
- [ ] Add troubleshooting guide for common failures (model picker not found, New Chat doesn't open)

## Contact & Context

- **Built**: December 7, 2025
- **Target panel for testing**: "Testing window functionality - desktop-agent-automation" (Sync Desktop)
- **Flags default to OFF** for safety
- **Requires**: `tasks/generated_prompts/latest.txt` to exist with valid prompts
- **Master prompt system**: Already generates up to 20 task prompts via OpenAI, now consumed by this follow-through
