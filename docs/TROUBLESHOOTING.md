# Troubleshooting Guide for Desktop Agent Automation

**Version:** 1.1  
**Date:** December 11, 2025  
**Last Updated:** April 25, 2026

## Overview

This guide covers the most common failures encountered when setting up and running the desktop agent automation system. Issues are organized by category with symptoms, root causes, diagnostic steps, and solutions.

Windows and PowerShell are the primary operator environment for this repo. Where older examples still use POSIX syntax, prefer the PowerShell-style commands shown in the setup sections below.

For advanced recovery playbooks, deeper log analysis, and edge-case scenarios (zero-bounds buttons, multi-desktop reliability, advanced rate limiting, prompt seeding internals, model picker changes, and clipboard/reading issues), see `docs/TROUBLESHOOTING_EXTENDED.md`.

## Quick Diagnosis

### Common Error Messages & Immediate Fixes

| Error Message                                                         | Immediate Fix                                                                                  |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `Can not move cursor. ButtonControl's BoundingRectangle is (0,0,0,0)` | Window is minimized or UI element not visible. Restore window and ensure VS Code is active.    |
| `OpenAI API key required`                                             | Set `OPENAI_API_KEY` environment variable                                                      |
| `Rate limit exceeded`                                                 | Wait 20 minutes for cooldown, reduce automation frequency                                      |
| `No VS Code windows found`                                            | Ensure VS Code is running and windows are not minimized                                        |
| `Window handle invalid`                                               | Restart VS Code windows, clear window cache                                                    |
| `ImportError: No module named 'openai'`                               | Run `pip install -r requirements.txt`                                                          |
| `Failed to switch to desktop`                                         | Check virtual desktop names, ensure pyvda is installed                                         |
| `strict_contract_rejected` / `Sandbox strict response rejected`       | Check the primary strict rejection and follow `docs/ORCHESTRATION_V1_STRICT_RESPONSE_GUIDE.md` |

## Orchestration V1 Strict Response

If Orchestration V1 rejects a strict response, start with the first rejection code surfaced in the payload.

- `response_timeout`: no acceptable response was observed before the deadline.
- `strict_contract_rejected`: the reply violated framing, JSON, or schema rules.
- `sandbox_contract_rejected`: sandbox self-test reply violated triage-only safety rules.
- `ambiguous_repo_window`: panel fallback saw multiple matching repo windows and needs an explicit window id.

Use the `strict_response` object in CLI JSON output or `operator_guidance` in poll diagnostics, then follow `docs/ORCHESTRATION_V1_STRICT_RESPONSE_GUIDE.md` for exact next actions.

## Orchestration V1 Operator Triage

Use the operator runbook when the issue is not limited to strict payload content:

- `docs/ORCHESTRATION_V1_OPERATOR_RUNBOOK.md`

Start with these buckets:

| Surface           | Check first                                               | Typical next action                                                         |
| ----------------- | --------------------------------------------------------- | --------------------------------------------------------------------------- |
| Preflight         | `repo_diagnostics[].selection.reason_code`                | Rerun preflight, move window onto active desktop, or use explicit window id |
| Readiness-only    | `dispatch_readiness.reason_code`                          | Bring target window foreground, expose chat input, rerun readiness          |
| Live pilot        | `pilot.status` and `decision_reason`                      | Inspect `pilot.window_match_diagnostics` and response source                |
| Strict live pilot | `strict_response.reason_code` and `primary_reject_reason` | Follow the strict response guide                                            |
| Task selection    | `diagnostics.selection.*`                                 | Inspect allowlist and blocked title terms instead of window state           |

Common orchestration v1 reason codes:

- `repo_window_detected_win32_only`: repo window exists but is cloaked or off-desktop.
- `ambiguous_repo_window`: multiple repo windows are eligible; use `--pilot-window-id`.
- `target_not_foreground`: wrong foreground window after readiness probe.
- `pilot_response_timeout`: no structured reply was accepted before timeout.
- `title_contains_blocked_term`: task selection was rejected by the pilot allowlist.

## Copilot Usage Monitor

The Copilot usage monitor runs inside the standard `python run_automation.py` process when `ENABLE_COPILOT_USAGE_MONITOR=true`.

Quick checks:

- Verify startup output includes `Copilot usage monitor started`.
- Confirm `COPILOT_USAGE_MONITOR_INTERVAL_SECONDS` is set to the intended polling cadence.
- Review persisted cost-tracker telemetry for `copilot_usage_monitor` source entries if status-bar reads are succeeding.

Common issues:

- If no data is recorded, ensure the main automation loop is the process you launched; `scripts/orchestration_v1.py` does not host the recurring monitor.
- If polls fail repeatedly, confirm a VS Code window with the Copilot status bar entry is visible to UI Automation.

## Setup Issues

### 1. Installation Failures

**Symptoms:**

- `ModuleNotFoundError` when running scripts
- `command not found: master`
- Import errors for `openai`, `uiautomation`, etc.

**Root Causes:**

- Incomplete pip install
- Virtual environment not activated
- Missing system dependencies
- PATH not configured for console scripts

**Diagnostic Steps:**

1. Check if virtual environment is active: `Get-Command python` should resolve to the `.venv` interpreter
2. Verify packages: `pip list | Select-String openai`
3. Test console script: `master --help`

**Solutions:**

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .[dev]

# For Windows console script issues
Copy-Item master.cmd $env:LOCALAPPDATA\Microsoft\WindowsApps\
```

**Prevention Tips:**

- Always activate virtual environment before running commands
- Use `pip install -e .[dev]` after cloning
- Keep requirements.txt synchronized with pyproject.toml

### 2. Configuration Failures

**Symptoms:**

- Buttons are not being clicked
- VS Code windows are skipped
- Automation reports no eligible panels

**Root Causes:**

- VS Code window titles don't match detection rules
- Copilot panel is not visible or focused
- UI layout changed after updates

**Diagnostic Steps:**

1. Verify VS Code is running with Copilot visible
2. Check detection rules in `automation/config.py`
3. Run the standard automation and watch console output: `python run_automation.py`

**Solutions:**

```powershell
# Run the standard automation loop
python run_automation.py

# Optional: verify vision-based detection without clicking
python -m automation.desktop_auto_allow_agent --dry-run --once
```

**Prevention Tips:**

- Revisit window title patterns after VS Code updates
- Keep Copilot panel open on each desktop you want scanned
- Avoid changing window titles during long runs

### 3. Environment Variable Issues

**Symptoms:**

- Master agent doesn't run
- API calls fail
- File paths not resolved

**Root Causes:**

- Missing required environment variables
- Incorrect path formats
- Variable scope issues

**Diagnostic Steps:**

1. Check variables: `echo $OPENAI_API_KEY`
2. Verify paths exist: `ls "$MASTER_AGENT_DOCS_ROOT"`
3. Test variable scope: restart shell after setting

**Solutions:**

```powershell
# Required variables for Windows
$env:OPENAI_API_KEY = "sk-your-key-here"
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# For Linux/Mac
export OPENAI_API_KEY="sk-your-key-here"
export ENABLE_FINISHED_PANEL_FOLLOWUPS=true
```

**Prevention Tips:**

- Use `.env` file for persistent variables
- Document required variables in team setups
- Validate variables in startup scripts

## Runtime Issues

### 4. Window Detection Failures

**Symptoms:**

- `No VS Code windows found`
- Buttons not being clicked
- `Window handle invalid` errors

**Root Causes:**

- VS Code windows minimized
- Virtual desktop issues
- Window title changes
- UI automation timeouts

**Diagnostic Steps:**

1. Run debug script: `python debug/debug_windows.py`
2. Check window titles in `window_list.txt`
3. Verify virtual desktops: `python debug/debug_virtual_desktops.py`

**Solutions:**

```bash
# Restore all VS Code windows
# Ensure windows are not minimized
# Check virtual desktop names match configuration

# Clear window cache if handles are stale
rm automation/window_cache.json
```

**Prevention Tips:**

- Keep VS Code windows visible
- Use consistent window titles
- Monitor virtual desktop names

### 5. Button Clicking Failures

**Symptoms:**

- `Can not move cursor. ButtonControl's BoundingRectangle is (0,0,0,0)`
- Buttons found but not clickable
- UI elements not responding

**Root Causes:**

- Windows minimized or behind other windows
- UI loading delays
- Coordinate drift
- VS Code UI updates

**Diagnostic Steps:**

1. Check if VS Code is foreground window
2. Verify button visibility manually
3. Test with debug script: `python debug/debug_buttons_all_desktops.py`

**Solutions:**

```bash
# Bring VS Code to foreground
# Ensure Copilot panel is visible
# Recapture button coordinates if needed

# For persistent issues, increase delays
$env:BUTTON_CLICK_DELAY = "0.5"
```

**Prevention Tips:**

- Keep VS Code as foreground application
- Avoid overlapping windows
- Recalibrate coordinates periodically

### 6. Virtual Desktop Issues

**Symptoms:**

- `Failed to switch to desktop`
- Windows not found on expected desktop
- Automation misses windows

**Root Causes:**

- Incorrect desktop names
- pyvda library issues
- Desktop switching race conditions

**Diagnostic Steps:**

1. List desktops: `python debug/debug_virtual_desktops.py`
2. Check desktop names match config
3. Test manual switching

**Solutions:**

```python
# Update desktop names in config
WINDOW_PRIORITY_PATTERNS = [
    "tf",      # Adjust to match actual desktop names
    "trading",
]
```

**Prevention Tips:**

- Use consistent desktop naming
- Test desktop switching manually
- Handle desktop creation/deletion

## API Issues

### 7. Rate Limiting

**Symptoms:**

- `Rate limit exceeded` messages
- 20-minute cooldowns triggering frequently
- Reduced automation effectiveness

**Root Causes:**

- Too many Allow clicks per hour
- API quota exhaustion
- Inefficient clicking patterns

**Diagnostic Steps:**

1. Check metrics: `tail -f logs/allow_metrics.jsonl`
2. Monitor rate: `python scripts/analyze_logs.py`
3. Review cooldown frequency

**Solutions:**

```python
# Reduce click frequency
MAX_ALLOWS_PER_HOUR = 50  # Conservative setting

# Increase intervals
SCAN_INTERVAL_SECONDS = 90  # Slower scanning
```

**Prevention Tips:**

- Monitor allow_metrics.jsonl regularly
- Adjust rates based on usage patterns
- Implement gradual rate reduction

### 8. OpenAI API Failures

**Symptoms:**

- `Error calling OpenAI API`
- Authentication failures
- Cost tracking errors

**Root Causes:**

- Invalid API key
- Network connectivity
- API quota exceeded
- Model availability issues

**Diagnostic Steps:**

1. Test API key: `python -c "import openai; openai.api_key='your-key'; print('OK')"`
2. Check network: `ping api.openai.com`
3. Review API dashboard for quotas

**Solutions:**

```bash
# Verify API key format
export OPENAI_API_KEY="sk-proj-..."  # Use project-based key

# Check quota and billing
# Visit https://platform.openai.com/usage
```

**Prevention Tips:**

- Monitor API usage dashboard
- Set up billing alerts
- Keep API keys secure and rotated

### 9. Cost Tracking Issues

**Symptoms:**

- Cost reports not updating
- Inaccurate spending data
- Missing cost_tracker.json

**Root Causes:**

- File permission issues
- Concurrent access conflicts
- JSON corruption

**Diagnostic Steps:**

1. Check file: `ls -la automation/cost_tracker.json`
2. Validate JSON: `python -c "import json; json.load(open('automation/cost_tracker.json'))"`
3. Review permissions

**Solutions:**

```bash
# Reset cost tracker if corrupted
rm automation/cost_tracker.json
# Restart automation to recreate

# Check file permissions
chmod 644 automation/cost_tracker.json
```

**Prevention Tips:**

- Backup cost_tracker.json regularly
- Handle file locks in multi-process scenarios
- Validate JSON before writing

## UI Issues

### 10. Panel Seeding Failures

**Symptoms:**

- Prompts not sending to panels
- `Failed to seed panel` errors
- Inactive panels not responding

**Root Causes:**

- Safety gates not enabled
- Panel state detection issues
- Text input failures

**Diagnostic Steps:**

1. Check environment variables: `echo $ENABLE_SEND_TO_INACTIVE_PANELS`
2. Verify panel states: `cat automation/panel_state.json`
3. Test manual input

**Solutions:**

```bash
# Enable required safety gates
export ENABLE_SEND_TO_INACTIVE_PANELS=true
export ENABLE_FINISHED_PANEL_FOLLOWUPS=true

# Reset panel states if corrupted
rm automation/panel_state.json
```

**Prevention Tips:**

- Always enable safety gates for production
- Monitor panel_state.json for corruption
- Test panel seeding manually first

### 11. Panel Alignment Issues

**Symptoms:**

- Windows move unexpectedly
- Panels not in configured positions
- DPI scaling problems

**Root Causes:**

- Windows DPI virtualization
- Monitor configuration changes
- VS Code window management

**Diagnostic Steps:**

1. Check current layout: `python scripts/align_panels.py --dry-run`
2. Verify monitor setup
3. Test alignment: `python scripts/align_panels.py`

**Solutions:**

```bash
# Realign panels
python scripts/align_panels.py --auto-grid --desktop current

# Recapture layout after monitor changes
python scripts/align_panels.py --configure --desktop current
```

**Prevention Tips:**

- Run alignment after Windows updates
- Use consistent monitor configurations
- Automate alignment in startup scripts

### 12. Focus Terminal Alerts

**Symptoms:**

- Unexpected audio alerts
- "Focus Terminal" notifications
- False positive alerts

**Root Causes:**

- VS Code terminal focus detection
- Alert deduplication failures
- User activity conflicts

**Diagnostic Steps:**

1. Check alert settings: `echo $FOCUS_TERMINAL_SPEAK_ALERTS`
2. Review deduplication: `echo $FOCUS_TERMINAL_DEDUPE_MINUTES`
3. Monitor alert frequency

**Solutions:**

```bash
# Adjust alert settings
export FOCUS_TERMINAL_SPEAK_ALERTS=false  # Disable audio
export FOCUS_TERMINAL_DEDUPE_MINUTES=60   # Reduce frequency
```

**Prevention Tips:**

- Configure alerts based on environment
- Use longer deduplication periods
- Disable audio in shared spaces

## Performance Issues

### 13. High CPU/Memory Usage

**Symptoms:**

- System slowdown
- High resource consumption
- Automation becoming unresponsive

**Root Causes:**

- Too frequent scanning
- Memory leaks in UI automation
- Large screenshot processing

**Diagnostic Steps:**

1. Monitor process: `top -p $(pgrep -f automation)`
2. Check scan intervals
3. Review screenshot sizes

**Solutions:**

```python
# Increase scan intervals
MIN_SCAN_INTERVAL_SECONDS = 1.0  # Reduce frequency

# Use selective monitoring
# Only monitor specific monitors/quadrants
python -m automation.desktop_auto_allow_agent --monitors 0,2 --quadrant bottom-left
```

**Prevention Tips:**

- Use appropriate scan intervals
- Limit monitor coverage
- Monitor system resources

### 14. Automation Freezing

**Symptoms:**

- Script stops responding
- No log updates
- Hotkeys not working

**Root Causes:**

- UI automation deadlocks
- Network timeouts
- Infinite loops in error handling

**Diagnostic Steps:**

1. Check process status: `ps aux | grep automation`
2. Review recent logs
3. Test manual intervention

**Solutions:**

```bash
# Kill stuck process
pkill -f automation

# Restart with verbose logging
python -m automation.orchestrator --verbose

# Use timeout protection
timeout 3600 python -m automation.orchestrator
```

**Prevention Tips:**

- Implement watchdog timers
- Use proper error handling
- Monitor process health

### 15. Log Analysis Issues

**Symptoms:**

- Logs not rotating
- Missing log entries
- Log file corruption

**Root Causes:**

- File permission issues
- Disk space exhaustion
- Concurrent write conflicts

**Diagnostic Steps:**

1. Check disk space: `df -h`
2. Verify permissions: `ls -la logs/`
3. Test log writing: `echo "test" >> logs/test.log`

**Solutions:**

```bash
# Rotate logs manually
mv logs/@AutomationLog.txt logs/@AutomationLog.txt.backup
touch logs/@AutomationLog.txt

# Check and free disk space
# Clean old backups
```

**Prevention Tips:**

- Monitor disk space
- Implement log rotation
- Use atomic writes for logs

### 16. UI Focus Loss

**Symptoms:**

- Automation loses focus on VS Code windows
- Interactions fail due to focus issues

**Root Causes:**

- Other applications stealing focus
- Timing issues with focus management
- FOCUS_TERMINAL_DEDUPE_MINUTES too short

**Diagnostic Steps:**

1. Check focus settings: `echo $FOCUS_TERMINAL_DEDUPE_MINUTES`
2. Monitor for focus stealing applications

**Solutions:**

```bash
# Adjust focus deduplication
export FOCUS_TERMINAL_DEDUPE_MINUTES=60

# Disable alerts if distracting
export FOCUS_TERMINAL_SPEAK_ALERTS=false
```

**Prevention Tips:**

- Close unnecessary applications
- Use focus lock tools
- Increase deduplication time

### 17. OpenAI API Errors

**Symptoms:**

- API call failures
- Authentication errors
- Rate limit errors

**Root Causes:**

- Invalid OPENAI_API_KEY
- Network issues
- Quota exceeded

**Diagnostic Steps:**

1. Verify API key: `echo $OPENAI_API_KEY`
2. Test connectivity: `ping api.openai.com`
3. Check OpenAI dashboard

**Solutions:**

```bash
# Set correct API key
export OPENAI_API_KEY="sk-proj-..."

# Check quota
# Visit https://platform.openai.com/usage
```

**Prevention Tips:**

- Monitor API usage
- Set billing alerts
- Use valid keys

### 18. Keep/New Chat Ordering Issues

**Symptoms:**

- Wrong button clicked in Copilot chat
- Keep and New Chat buttons in unexpected order

**Root Causes:**

- VS Code UI changes
- Button detection logic not accounting for order
- ENABLE_NEW_CHAT_RETRY disabled

**Diagnostic Steps:**

1. Check retry setting: `echo $ENABLE_NEW_CHAT_RETRY`
2. Manually verify button order in VS Code

**Solutions:**

```bash
# Enable retry for new chat
export ENABLE_NEW_CHAT_RETRY=true

# Update button detection logic if needed
```

**Prevention Tips:**

- Enable retry feature
- Monitor for UI changes
- Test button detection

### 19. Usage Monitor Drift

**Symptoms:**

- Cost tracking inaccurate
- Usage reports not matching actual API usage
- Drift in monitored values

**Root Causes:**

- Incorrect COST_TRACKER_MODEL_RATES
- Wrong COST_TRACKER_VISION_COST_PER_IMAGE
- Model rate changes not updated

**Diagnostic Steps:**

1. Check model rates: `echo $COST_TRACKER_MODEL_RATES`
2. Verify vision cost: `echo $COST_TRACKER_VISION_COST_PER_IMAGE`
3. Compare with OpenAI pricing

**Solutions:**

```bash
# Update model rates
export COST_TRACKER_MODEL_RATES='{"gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01}}'

# Set vision cost
export COST_TRACKER_VISION_COST_PER_IMAGE=0.0013
```

The built-in defaults (gpt-4o-mini / gpt-4o / gpt-4-turbo) are clearly marked as **approximate** in the README. If you skip the override, expect estimates to drift from your invoice. Set `COST_TRACKER_MODEL_RATES` any time OpenAI publishes new pricing.

**Prevention Tips:**

- Keep rates updated with OpenAI changes
- Verify costs periodically
- Use accurate pricing data

## Log Analysis Tips

### Interpreting Common Log Patterns

**Rate Limit Detection:**

```text
Rate limit detected - entering cooldown
```

- Check allow_metrics.jsonl for click frequency
- Verify MAX_ALLOWS_PER_HOUR setting
- Consider reducing automation intensity

**Window Detection Issues:**

```text
No VS Code windows found on desktop
```

- Run `python debug/debug_windows.py`
- Check if windows are minimized
- Verify desktop names

**API Errors:**

```text
Error calling OpenAI API: 429
```

- Check API quota and billing
- Implement exponential backoff
- Reduce API call frequency

**UI Automation Failures:**

```text
ButtonControl's BoundingRectangle is (0,0,0,0)
```

- Window is not visible or minimized
- UI element not rendered
- Coordinates need recalibration

### Using Debug Scripts

```bash
# Window detection
python debug/debug_windows.py

# Button finding
python debug/debug_buttons_all_desktops.py

# Virtual desktop info
python debug/debug_virtual_desktops.py

# Comprehensive debugging
python debug/debug_comprehensive.py
```

## Getting Help

If these solutions don't resolve your issue:

1. **Collect diagnostics:**
   - Run debug scripts and save output
   - Copy relevant log excerpts
   - Note system configuration

2. **Check existing issues:**
   - Review docs/Todo.md for known issues and HANDOVER.md for current next actions
   - Check recent commits for fixes

3. **Provide context when reporting:**
   - System: Windows version, VS Code version
   - Configuration: key environment variables
   - Steps to reproduce
   - Expected vs actual behavior

---

## VS Code Copilot Panel Troubleshooting (Desktop Agent Automation)

The sections below focus specifically on the VS Code Copilot chat automation path (panel detection, prompt seeding, model selection, state management, and orchestrator behavior). Use them in combination with the main sections above.

### Quick Diagnosis Flow (Panels & Seeding)

```text
START
 ├─► Panels visible in VS Code?
 │     ├─► NO → Fix layout / open Copilot → Panel Detection
 │     └─► YES
 │
 ├─► Logs say "Found 0 chat panels"?
 │     ├─► YES → Panel Detection
 │     └─► NO
 │
 ├─► Prompts missing from Copilot input box?
 │     ├─► YES → Prompt Seeding
 │     └─► NO
 │
 ├─► Wrong model or model not changing?
 │     ├─► YES → Model Selection
 │     └─► NO
 │
 ├─► `panel_state.json` disagrees with on-screen state?
 │     ├─► YES → State Management
 │     └─► NO
 │
 └─► Orchestrator not generating prompts or very slow?
       └─► Master Orchestrator / Performance
```

### Panel Detection – Common Patterns

**Command:**

```powershell
python -m automation.panel_tracker --list --verbose
```

**Expected output (success) ✅:**

- At least one entry with:
  - A VS Code window title containing your repo name.
  - Panel type indicating a Copilot chat panel.
  - A non-null handle and desktop index.

**If output is empty or only shows wrong windows:**

- Check that VS Code is open and not minimized.
- Bring the correct window to the foreground.
- Re-run with cache disabled:

  ```powershell
  python -m automation.panel_tracker --list --no-cache
  ```

### Prompt Seeding – "Could not find input box"

**Command (state check):**

```powershell
python -c "from automation.panel_state import load_panel_state; print(load_panel_state())"
```

**Expected output ✅:**

- The target panel entry exists and is marked `IDLE` before seeding.

**Typical failing log:**

```text
ERROR automation.panel_seeding: Could not find input box for panel
```

**Fix:**

1. Ensure Copilot finished streaming and the input box is visible.
2. Run automation again, ideally in dry-run first:

   ```powershell
   master --run vs-code-automation --dry-run
   ```

### Model Selection – Picker & Target Model

**Debug command:**

```powershell
python -m automation.panel_ui --debug-model-picker
```

**Expected output ✅:**

- Logs showing that the model picker control was located and a list of model entries was read.

**Common variations:**

- Picker exists but is hidden behind a dialog → close dialog and retry.
- Target model label changed → update `automation/config.json` model names.

### State Management – Quick Reset

**When you see:**

```text
JSONDecodeError loading automation/panel_state.json
```

**Safe reset procedure:**

```powershell
Copy-Item automation/panel_state.json automation/panel_state.json.bak
Remove-Item automation/panel_state.json
master --run vs-code-automation
```

### Master Orchestrator – Dry Runs

**Commands:**

```powershell
# Validate credential readiness before a live refresh
python -m automation.master_prompt_orchestrator --check-openai-credentials

# Generate prompts without applying them
python -m automation.master_prompt_orchestrator --dry-run --max-docs 5
```

**Expected output ✅:**

- Credential check prints `OPENAI READY: ...` when the configured key is usable.
- A short list of documents and candidate prompts.

Successful credential check shape:

```text
OPENAI READY: model=gpt-5.4 credential_source=process environment
```

Invalid-key credential check shape:

```text
ERROR: OpenAI credentials are not ready for automation.master_prompt_orchestrator: authentication failed for OPENAI_API_KEY loaded from process environment (matches C:\Users\Pilot\Documents\Vs Code Projects\desktop-agent-automation\.env). OpenAI detail: Error code: 401 - {'error': {'message': 'Incorrect API key provided: ...', 'code': 'invalid_api_key'}, 'status': 401}. The secret value is external to repository code; replace it in the process environment or repo-root .env, then rerun `python -m automation.master_prompt_orchestrator --check-openai-credentials`.
```

Operator remediation steps for the exact credential blocker above:

1. Replace the placeholder or revoked `OPENAI_API_KEY` with a real, active key.
2. Update the winning source first: the current process environment. If you also keep a repo-root `.env`, update it to the same value so future shells stay aligned.
3. Open a fresh shell after changing the environment if the current terminal inherited the old key.
4. Re-run `python -m automation.master_prompt_orchestrator --check-openai-credentials`.
5. Proceed to a live refresh only after that command prints `OPENAI READY: ...`.

Precedence note:

- Resolution order is process environment first, then the repo-root `.env` file.
- If the message says `loaded from process environment (matches ...\.env)`, precedence is not the blocker; both sources currently contain the same value.

If the credential check fails, the message now tells you whether `OPENAI_API_KEY` is missing, whether the repo-root `.env` was found, and whether the blocker is external secret material rather than repository code.

If you repeatedly see "No documents found" or "all prompts filtered", revisit repo detection and quality thresholds as described in the main troubleshooting sections.

### Master Orchestrator - Missing WSL docs source

If the upstream `contracts/docs` path is missing, the orchestrator warning is now explicit. Run this first to get a deterministic readiness result for every configured repo:

```powershell
python -m automation.master_prompt_orchestrator --readiness-check --json
```

If the default trading-system layout is in use, the exact directory that must exist for `contracts` is:

- `\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs`

If only `contracts` diverged from that layout, `TRADING_SYSTEM_ROOT_WIN` is not the right fix. That root feeds the default paths for `contracts`, `TF`, and `Trading` together. Changing it would repoint `TF` and `Trading` even if they are already correct.

Expect a warning shaped like this when the repo root is reachable but that docs directory is absent:

```text
WARNING: [ORCHESTRATOR] Repo 'contracts' docs source external_docs_missing. Path: \wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs. Repo root: \wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts. Expected relative path: docs. Cache fallback: using cached docs from state\docs_cache\contracts. Detail: Configured repo root is reachable at \wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts, but the expected docs directory is missing at \wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs.
```

Interpretation:

- `external_docs_missing` means the WSL repo root is reachable but the expected docs directory does not exist.
- `repo_misconfiguration` means the configured docs path itself is suspect and should be fixed in `MASTER_AGENT_REPO_CONFIGS` or the CLI `--repos` input.
- `upstream_unreachable` means the WSL repo root or UNC share is unavailable, so fix WSL access before debugging `contracts/docs` contents.
- `Cache fallback: using cached docs ...` means prompt generation can still proceed from the last good snapshot.
- `no cached docs available ...` means the `contracts` repo cannot seed prompts until the upstream docs path is restored and read successfully at least once.

Recovery steps:

1. Check whether `\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs` exists.
2. If only `contracts` moved, override `MASTER_AGENT_REPO_CONFIGS` instead of `TRADING_SYSTEM_ROOT_WIN`:

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

    This keeps `TF` and `Trading` on their existing live docs while redirecting only `contracts` to the validated file-backed sources.
3. Re-run `python -m automation.master_prompt_orchestrator --readiness-check --json` and confirm `contracts`, `TF`, and `Trading` all report `"status": "live_ready"`.
4. Re-run `python -m automation.master_prompt_orchestrator --dry-run --max-docs 5`.
5. Confirm `contracts` documents are listed again and that `state/docs_cache/contracts/` is populated after a successful live read.

---

_For the latest updates, check the repository regularly. This guide is maintained alongside the codebase._
