# Extended Troubleshooting Guide

> This guide complements `docs/TROUBLESHOOTING.md` with deeper failure analysis, diagnostics, and recovery recipes for advanced operators.

Unless you explicitly override the path variables, the state files referenced in examples now resolve under `AUTOMATION_PRIVATE_ROOT` (default `private/`).

## 1. Zero-Bounds Button Errors

### 1.1 Symptoms

- Repeated log lines in `@AutomationLog.txt` or `automation/auto_allow.log`:
  - `Can not move cursor. ButtonControl's BoundingRectangle is (0,0,0,0)`
  - `TextControl's BoundingRectangle is (0,0,0,0)`
- Occasional `[ZERO_BOUNDS]` annotations, for example:
  - `[ZERO_BOUNDS] Button 'Allow (Ctrl+Enter)' has zero bounds ... - skipping for 2min`
- Allow / Keep / Try Again buttons clearly visible to you in the UI, but the agent refuses to click them.

### 1.2 Root Causes (Patterns from Logs)

From `@AutomationLog.txt` the failure has two dominant patterns:

1. **Hidden / non-rendered controls**
   - Bounding rectangle is exactly `(0,0,0,0)[0x0]` even when the control exists in the UIA tree.
   - Typically occurs when:
     - VS Code window is minimized or completely off-screen.
     - The Copilot chat panel is collapsed or scrolled out of view.
     - Another top-level dialog has focus (e.g., VS Code update, new chat confirmation).

2. **Transient layout during animation**
   - Bursts of zero-bounds errors for a few seconds while VS Code is animating panel open/close or resizing.
   - The agent may recover automatically, but repeated entries indicate it is sampling too aggressively while the UI is in flux.

The `[ZERO_BOUNDS] ... skipping for 2min` entries indicate that the agent detected a persistently zero-bound button and deliberately backs off to avoid hammering a broken UI state.

### 1.3 Diagnostics

1. **Confirm in logs**
   - Open `@AutomationLog.txt` and search for `BoundingRectangle is (0,0,0,0)`.
   - Check if the errors cluster around specific windows or times.

2. **Check window visibility and focus**
   - Ensure the target VS Code window is **restored**, not minimized.
   - Ensure the Copilot chat panel is visible and scrolled so that the buttons are on screen.
   - Verify no modal dialogs are covering the chat pane.

3. **Use debug scripts to inspect controls**

   ```powershell
   # List all buttons on current desktop
   python debug\debug_list_buttons.py

   # Scan VS Code windows and verify button bounds
   python debug\debug_buttons_all_desktops.py
   ```

   - Look for the relevant `Allow`, `Keep edits`, or `Try Again` controls and confirm they have non-zero bounding rectangles.

### 1.4 Recovery Procedures

1. **Quick manual recovery**
   - Restore all VS Code windows.
   - Bring the target window to the foreground.
   - Manually scroll the chat so the Allow/Keep/Try Again buttons are fully visible.
   - Resume the master agent (`master`) and observe if errors clear.

2. **Desktop / window tree reset**

   ```powershell
   # Stop any running automation
   Ctrl+C  # in the terminal running `master`

   # (Optional) Reset desktop failure tracking
   # Causes re-check of all desktops next cycle
   python -c "from automation.desktop.reliability import reset_all_desktop_failures; reset_all_desktop_failures()"

   # Restart the master orchestrator
   master
   ```

3. **Scroll-into-view enforcement**
   - If zero-bounds errors persist for a specific window, open that window and manually interact with the Copilot panel:
     - Click inside the panel.
     - Scroll to the bottom.
     - Trigger one manual Allow click to “warm up” the UIA tree.

4. **Long-running mitigation**
   - If you regularly see clusters of zero-bounds errors:
     - Avoid leaving VS Code minimized for long periods while automation is active.
     - Keep Copilot panels open and avoid overlapping windows in front of them.

---

## 2. Desktop Switching Failures

### 2.1 Symptoms

- Logs report errors such as:
  - `Failed to switch to desktop`
  - `Desktop 'TF' not found!`
- Automation only acts on windows from a single desktop.
- `debug/debug_virtual_desktops.py` shows more desktops than the agent is actually checking.

### 2.2 Root Causes

- `DESKTOPS_TO_CHECK` in `automation/config.py` or `automation/config.json` does not match actual desktop names.
- `pyvda` cannot enumerate desktops (API or permission issues).
- In numeric mode, the system never fully “syncs” to desktop 1, so keyboard-based switching drifts.
- Desktop reliability tracking (`automation/desktop/reliability.py`) has marked a desktop as failed and is skipping it.

### 2.3 Diagnostics

1. **Inspect configured desktops**

   ```powershell
   # Show relevant desktop config
   python - << 'EOF'
   from automation.config import DESKTOPS_TO_CHECK
   print("DESKTOPS_TO_CHECK:", DESKTOPS_TO_CHECK)
   EOF
   ```

2. **Enumerate real desktops (names)**

   ```powershell
   python debug\debug_virtual_desktops.py
   ```

   - Compare the printed names with `DESKTOPS_TO_CHECK`.

3. **Check desktop reliability state**

   ```powershell
   python - << 'EOF'
   from automation.desktop.reliability import get_all_failure_stats
   import json
   print(json.dumps(get_all_failure_stats(), indent=2))
   EOF
   ```

   - High `failures` counts for specific desktop numbers indicate a skip condition.

### 2.4 Recovery Procedures

1. **Fix configuration mismatches**
   - Update `DESKTOPS_TO_CHECK` to one of the following patterns:

     ```python
     # a) Single current desktop only
     DESKTOPS_TO_CHECK = [0]

     # b) Named desktops using pyvda (recommended)
     DESKTOPS_TO_CHECK = ["TF", "Trading"]

     # c) Auto-detect VS Code desktops + explicit priorities
     DESKTOPS_TO_CHECK = ["TF", "Trading", "auto"]
     ```

   - Restart the automation after changing config.

2. **Reset reliability tracking**

   ```powershell
   python - << 'EOF'
   from automation.desktop.reliability import reset_all_desktop_failures
   reset_all_desktop_failures()
   EOF
   ```

3. **Force numeric desktop resync (legacy mode)**
   - If using numeric IDs (e.g., `DESKTOPS_TO_CHECK = [1, 2, 3]`):

     ```powershell
     python - << 'EOF'
     from automation.desktop.switcher import reset_desktop_sync
     reset_desktop_sync()
     EOF
     ```

   - The next switch will drive the system back to desktop 1 and then step to the desired desktop.

---

## 3. Rate Limiting and Recovery

### 3.1 Symptoms

- Frequent `Rate limit exceeded` messages in logs.
- `Try Again` buttons appearing shortly after Allow clicks.
- Long periods of inactivity where the auto-allow agent does nothing.

### 3.2 How Rate Limiting Is Detected

There are two cooperating mechanisms:

1. **Per-hour Allow limit (`automation/rate_limit/tracker.py`)**
   - Tracks Allow clicks in a rolling window of `ALLOW_EVENT_RETENTION_MINUTES`.
   - Enforces a maximum of `MAX_ALLOWS_PER_HOUR` clicks.
   - `get_rate_limit_wait_seconds()` returns the required wait before the next click.

2. **UI-based Try Again detection (`automation/ui/button_clicker.py`)**
   - After an Allow click, the agent searches the window for `Try Again` / `Try Again (Ctrl+Enter)` buttons.
   - If found, `trigger_rate_limit_cooldown()`:
     - Starts a global cooldown via `automation.rate_limit.cooldown.start_cooldown()`.
     - Triggers an audio alert: “Rate limited. Waiting 5 minutes.”
     - Logs a prominent `RATE LIMITED!` message.

### 3.3 Diagnostics

1. **Inspect recent Allow activity**

   ```powershell
   # Tail allow metrics
   Get-Content automation\allow_metrics.jsonl -Tail 50

   # Quick snapshot via Python
   python - << 'EOF'
   from automation.rate_limit.tracker import get_metrics_snapshot, format_rate_status
   print(format_rate_status())
   print(get_metrics_snapshot())
   EOF
   ```

   `format_rate_status()` includes last 60 minutes and total Allow clicks.

2. **Check cooldown state (Try Again path)**
   - Search logs for `RATE LIMITED! 'Try Again' button appeared after Allow click.`
   - Manually open the affected VS Code window and verify that Copilot shows a rate-limited banner.

3. **Verify global cooldown configuration**
   - Inspect `TRY_AGAIN_COOLDOWN_MINUTES` and `MAX_ALLOWS_PER_HOUR` in `automation/config.py`.

### 3.4 Recovery Procedures

1. **Immediate manual cooldown**
   - Stop automation (`Ctrl+C` in the `master` terminal).
   - Wait at least **20–30 minutes** with minimal manual usage of Copilot.
   - Restart `master` and observe if `Try Again` buttons disappear.

2. **Tune allow aggressiveness**

   ```python
   # In automation/config.py
   MAX_ALLOWS_PER_HOUR = 50          # lower this if frequently limited
   ALLOW_EVENT_RETENTION_MINUTES = 60
   RATE_LIMIT_BUFFER_SECONDS = 30    # extra safety margin
   TRY_AGAIN_COOLDOWN_MINUTES = 5    # or higher for very constrained org quotas
   ```

   - After edits, restart the master orchestrator.

3. **Clear persisted allow events**

   ```powershell
   # Optional: reset historical event window
   Remove-Item automation\allow_events.json -ErrorAction SilentlyContinue
   ```

4. **Playbook: recovery after hard limit**
   1. Stop automation.
   2. Wait 30–60 minutes.
   3. Manually issue a single Copilot request to confirm recovery.
   4. Restart automation with **reduced** `MAX_ALLOWS_PER_HOUR`.
   5. Monitor `automation/allow_metrics.jsonl` for the next hour.

---

## 4. Panel State Corruption and Recovery

### 4.1 Symptoms

- `automation/panel_state.json` grows large or contains obviously stale panels.
- Finished panels never transition back to RUNNING/IDLE after updates.
- The master orchestrator keeps referring to old window titles or closed panels.

### 4.2 How Panel State Works

- `automation/panel_tracker_core.PanelTracker` persists panel metadata to `automation/panel_state.json`:
  - Status: `RUNNING`, `WAITING_ALLOW`, `RATE_LIMITED`, `IDLE`, `FINISHED`, `COMPLETED`, `STALE`, `NEEDS_INPUT`, `ERROR`.
  - Timestamps: `first_seen`, `last_allow_click`, `last_output_change`, `last_scanned`.
  - Transcript snapshots and last response classification.
- `update_panel_status()` periodically transitions panels based on timing thresholds:
  - Idle after no Allow clicks for `PANEL_IDLE_THRESHOLD_MINUTES`.
  - Finished after no output change for `PANEL_FINISHED_THRESHOLD_MINUTES`.
  - Stale if not scanned for `PANEL_STALE_THRESHOLD_MINUTES`.

### 4.3 Diagnostics

1. **Inspect raw panel state**

   ```powershell
   # Quick JSON preview
   Get-Content automation\panel_state.json -TotalCount 80
   ```

   - Look for panels with very old timestamps or repeated `STALE` status.

2. **Check loaded panels at runtime**

   ```powershell
   python - << 'EOF'
   from automation.panel_tracker_core import PanelTracker
   tracker = PanelTracker()
   print("Loaded panels:", len(tracker.panels))
   for key, panel in list(tracker.panels.items())[:10]:
       print(key, panel.status, panel.last_scanned)
   EOF
   ```

### 4.4 Recovery Procedures

1. **Soft reset: allow tracker to clean up**
   - Stop automation and restart `master`. `PanelTracker.__post_init__()` will:
     - Load existing state.
     - Normalize repo indices.
   - Let it run for one full idle/finished cycle so `update_panel_status()` can mark stale panels appropriately.

2. **Hard reset: delete corrupted state**

   ```powershell
   Stop-Process -Name python -ErrorAction SilentlyContinue  # if needed
   Remove-Item automation\panel_state.json -ErrorAction SilentlyContinue
   ```

   - On next run, `PanelTracker` starts from an empty state and rebuilds from fresh Allow/output events.

3. **Targeted cleanup via script (optional)**
   - You can write a one-off Python snippet that loads `PanelTracker`, drops specific stale keys, and re-saves. Prefer a full backup first.

---

## 5. Prompt Seeding Failures

### 5.1 Symptoms

- Finished panels never receive follow-up prompts.
- `automation/metrics.json` shows seeding attempts with `success=false`.
- Logs contain lines like:
  - `Could not open New Chat for finished panel`
  - `Failed to send text to chat`

### 5.2 How Prompt Seeding Works

- `automation/panel_seeding.process_finished_panels_with_prompts`:
  1. Calls `PanelTracker.update_panel_status()` and `get_finished_panels()`.
  2. Uses `panel_task_dispatcher` to reserve tasks/prompts for each finished panel.
  3. For each panel:
     - Ensures the VS Code window has focus (`_ensure_panel_window_focus`).
     - Opens **New Chat** via `_open_new_chat` (searches for `"New Chat"` button).
     - Optionally selects a model using the model picker.
     - Sends text using `panel_ui.send_text_to_chat`.
     - Records metrics (`record_prompt_seeding`, `record_assignment`).

### 5.3 Diagnostics

1. **Enable / verify finished panel follow-ups**

   ```powershell
   $env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
   ```

   - Or validate this in your environment/config.

2. **Inspect seeding metrics**

   ```powershell
   Get-Content automation\metrics.json | Select-String "prompt_seeding" -Context 0,3
   ```

   - Look for `success` flags and error messages.

3. **Check prompt feeds and repo mapping**
   - Ensure that for the target repo:
     - A task feed exists and has unassigned entries **or**
     - Legacy prompt blocks are available via `panel_task_dispatcher._load_prompt_blocks_for_repo`.

### 5.4 Recovery Procedures

1. **Fix model picker / New Chat selectors after VS Code updates**
   - If VS Code changes the label for **New Chat** or model picker:
     - Update `_find_new_chat_button` and `_find_model_picker_button` in `automation/panel_seeding.py` to search for the new names.

2. **Verify window focus before seeding**
   - Ensure VS Code windows are on-screen and not minimized.
   - If `_ensure_panel_window_focus` fails frequently, run:

     ```powershell
     python debug\debug_vscode_windows.py
     ```

     - Confirm that the window titles match expectations and that `SetActive` works.

3. **Rebuild prompt feeds**
   - If no tasks can be reserved for a repo:
     - Regenerate `tasks/generated_prompts` for that repo.
     - Re-run the master orchestrator to re-populate assignments.

---

## 6. Model Picker UI Changes

### 6.1 Symptoms

- Seeding succeeds, but the requested model is never selected.
- The model picker opens, but the agent does not click any item.
- Newly added models in VS Code are not recognized.

### 6.2 How Model Selection Works

- `panel_seeding._detect_model_label` maps prompt text hints to `MODEL_PICKER_LABELS`.
- `_find_model_picker_button` searches the VS Code window for a `MenuItemControl` whose `Name` contains `"pick model"`.
- `_select_model` clicks this button, waits briefly, then looks for a `MenuItemControl` with `Name` equal to the desired label.

### 6.3 Diagnostics and Updates

1. **Confirm current labels in VS Code**
   - Manually open the model picker and note the exact text of:
     - The picker button (e.g., `Pick model`, `Model: GPT-4o`, etc.).
     - Individual menu items (e.g., `GPT-4.1`, `GPT-4o mini`).

2. **Update label mappings**
   - In `automation/config.py`, update `MODEL_PICKER_LABELS` to match real menu item names.

3. **Update search heuristics if UI changes**
   - If the picker button no longer includes `"pick model"`:
     - Adjust `_find_model_picker_button` to look for the new substring (e.g., `"Model:"`).

---

## 7. Clipboard / Text Reading Issues

### 7.1 Symptoms

- `panel_input_reader.read_chat_input` returns empty strings even when text is present.
- Errors like `Error reading chat input: ...` printed to console.
- Clipboard contents unexpectedly changed after automation runs.

### 7.2 How Chat Input Reading Works

- `automation/panel_input_reader.py` uses a clipboard-based sequence:
  1. Save current foreground window.
  2. Clear clipboard via `Set-Clipboard`.
  3. Focus VS Code window and dismiss dialogs with `Escape`.
  4. Focus chat input (`Ctrl+L`).
  5. Select all (`Ctrl+A`), copy (`Ctrl+C`).
  6. Read clipboard via `Get-Clipboard`.
  7. Restore original foreground window.

### 7.3 Diagnostics

1. **Run a focused input read test**

   ```powershell
   # With a single VS Code window visible and focused on a Copilot chat
   python - << 'EOF'
   from automation.panel_input_reader import find_vscode_windows, read_chat_input
   wins = find_vscode_windows()
   print("windows:", len(wins))
   if wins:
       print(read_chat_input(wins[0]))
   EOF
   ```

2. **Check PowerShell clipboard commands**
   - Confirm that `Set-Clipboard` and `Get-Clipboard` work from your shell.

3. **Watch for conflicts with other clipboard tools**
   - Clipboard managers or security tools may intercept or block clipboard access.

### 7.4 Recovery Procedures

1. **Minimize interference**
   - Avoid using the keyboard/mouse while clipboard-based reads are running.
   - Keep a single visible VS Code window active when testing.

2. **Fallback to safe variant**
   - Use `read_chat_input_safe` when integrating into workflows that must not throw on failure.

3. **If clipboard is too unreliable**
   - Consider reducing how often clipboard-based reads are invoked.
   - If your environment forbids clipboard automation entirely, disable any features that require reading chat input via `panel_input_reader`.

---

## 8. Log Analysis Techniques

### 8.1 Quick filters

Use `Select-String` on Windows PowerShell to filter logs:

```powershell
# Zero bounds
Get-Content @AutomationLog.txt | Select-String "BoundingRectangle is (0,0,0,0)"

# Rate limiting
Get-Content automation\auto_allow.log | Select-String "RATE LIMITED"

# Desktop switching
Get-Content automation\auto_allow.log | Select-String "desktop" | Select-String "error|failed|not found"
```

### 8.2 Time-window slicing

```powershell
# Last 200 lines of the main automation log
Get-Content automation\auto_allow.log -Tail 200

# Follow logs in real time
Get-Content automation\auto_allow.log -Wait
```

### 8.3 Cross-referencing metrics

- Use `automation/metrics.json`, `automation/assignment_metrics.jsonl`, and `automation/allow_metrics.jsonl` together:
  - Correlate prompt seeding events with Allow click patterns.
  - Identify which repos and prompts are most likely to hit rate limits.

---

## 9. Step-by-Step Recovery Checklist

When the system appears “stuck” or misbehaving:

1. **Check basics**
   - VS Code windows visible and not minimized.
   - Copilot chat panels open, Allow/Send buttons visible.
   - `master` process running without exceptions.

2. **Scan for rate limits**
   - Look for `RATE LIMITED` and `Try Again` in logs.
   - If present, pause automation and wait 20–30 minutes.

3. **Verify desktops and windows**
   - Run `debug/debug_virtual_desktops.py`.
   - Run `debug/debug_vscode_windows.py`.
   - Fix `DESKTOPS_TO_CHECK` + reset reliability.

4. **Inspect panel state**
   - Preview `automation/panel_state.json`.
   - Delete the file if clearly corrupted or massively stale.

5. **Check prompt seeding**
   - Search `automation/metrics.json` for seeding attempts.
   - Validate model picker labels and New Chat labels.

6. **Reboot the automation stack**
   - Stop all automation processes.
   - Close and reopen VS Code windows.
   - Start `master` again.

If problems persist after this checklist, capture:
- A compressed copy of `automation/*.json*` and `automation/*.log`.
- A short screen recording of the VS Code UI.
- The exact commit and a description of recent VS Code / Copilot updates.

Then iterate on selectors and thresholds as needed.
