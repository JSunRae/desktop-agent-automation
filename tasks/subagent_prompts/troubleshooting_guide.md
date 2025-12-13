# Task: Create Troubleshooting Guide for Desktop Agent Automation

## Objective
Create a comprehensive troubleshooting guide (`docs/TROUBLESHOOTING.md`) that helps users diagnose and resolve common failures in the desktop agent automation system. The guide must be practical, well-organized, and cover the most frequent issues encountered in production.

## Scope Boundaries - CRITICAL
**IN SCOPE:**
- Document common error patterns and their resolutions
- Include debugging steps for panel detection issues
- Cover prompt seeding failures
- Document model picker interaction problems
- Explain log analysis procedures
- Provide resolution procedures for each issue category
- Include command examples and log excerpts
- Add quick reference troubleshooting flowchart

**OUT OF SCOPE:**
- Do NOT create new code or features
- Do NOT modify existing code (documentation only)
- Do NOT redesign the architecture
- Do NOT add new error handling (document existing behavior)
- Do NOT create additional tooling beyond documentation
- Do NOT modify other documentation files
- Do NOT include installation instructions (separate README section)

## Context
The desktop agent automation system (`automation/`) has these key components:
1. **Panel Detection** (`panel_tracker.py`, `panel_detection.py`) - Finds VS Code Copilot chat panels
2. **Prompt Seeding** (`panel_seeding.py`) - Sends prompts to panels
3. **Model Selection** (`panel_ui.py`) - Chooses AI model (Grok/Codex)
4. **State Management** (`panel_state.py`) - Tracks panel status
5. **Master Orchestrator** (`master_prompt_orchestrator.py`) - Generates prompts
6. **Metrics** (`metrics.py`) - Tracks usage and costs

Common failure points include:
- Panel not detected (wrong window, cache issues, desktop switching)
- Seeding fails (UI element not found, timing issues)
- Model picker not accessible (dialog blocked, element changed)
- State corruption (invalid JSON, race conditions)

## Requirements

### Document Structure
Create `docs/TROUBLESHOOTING.md` with these sections:

```markdown
# Troubleshooting Guide

## Table of Contents
1. Quick Diagnosis Flowchart
2. Common Issues and Solutions
   - Panel Detection Problems
   - Prompt Seeding Failures
   - Model Selection Issues
   - State Management Errors
   - Master Orchestrator Problems
   - Performance and Timing Issues
3. Debugging Tools and Commands
4. Log Analysis
5. Advanced Troubleshooting
6. When to Reset State
7. Getting Help

## 1. Quick Diagnosis Flowchart
[Flowchart helping users identify issue category quickly]

## 2. Common Issues and Solutions
[Each issue with: Symptoms, Cause, Solution, Prevention]
```

### Required Issue Coverage

#### 2.1 Panel Detection Problems

**Issue: No panels detected**
- **Symptoms**: Log shows "No panels found", "0 chat panels detected"
- **Cause**: VS Code not running, wrong window title, inactive desktop, cache stale
- **Solution**: Step-by-step debugging with commands
- **Prevention**: Best practices
- **Example log excerpt**: Show actual log output
- **Resolution commands**: Exact commands to run

**Issue: Wrong panel detected**
- **Symptoms**: Panel count mismatch, unexpected panel titles
- **Cause**: Multiple VS Code instances, title parsing issues
- **Solution**: Specific fix steps
- **Commands**: How to list and verify panels

**Issue: Cache shows stale panels**
- **Symptoms**: "Panel no longer exists", handle invalid errors
- **Cause**: Desktop switch, window closed, cache not refreshed
- **Solution**: Force cache refresh, revalidate handles
- **Prevention**: When to invalidate cache

#### 2.2 Prompt Seeding Failures

**Issue: "Could not find input box"**
- **Symptoms**: UI automation fails, element not found
- **Cause**: Timing issue, wrong panel state, UI changed
- **Solution**: Retry logic, verify panel state
- **Commands**: How to debug UI elements

**Issue: Seeding succeeds but prompt not applied**
- **Symptoms**: Panel marked as seeded but shows old content
- **Cause**: Clipboard failure, focus issues, send keys failed
- **Solution**: Verify clipboard, check focus
- **Commands**: Manual seeding test

**Issue: "Panel is finished, skipping seeding"**
- **Symptoms**: Panel detected as finished when idle
- **Cause**: False positive in finished detection
- **Solution**: Adjust detection logic parameters
- **Commands**: How to check panel classification

#### 2.3 Model Selection Issues

**Issue: "Model picker not found"**
- **Symptoms**: Cannot open model dropdown
- **Cause**: UI element changed, wrong panel type, dialog blocking
- **Solution**: Verify UI structure, check for dialogs
- **Commands**: Debug model picker state

**Issue: "Target model not found in list"**
- **Symptoms**: Model selection fails even when picker opens
- **Cause**: Model name mismatch, list not loaded
- **Solution**: Verify model names, wait for list load
- **Example**: Show model name variations

**Issue: Selection doesn't stick**
- **Symptoms**: Model reverts after selection
- **Cause**: Selection not confirmed, race condition
- **Solution**: Add confirmation wait, verify selection

#### 2.4 State Management Errors

**Issue: "panel_state.json is corrupted"**
- **Symptoms**: JSON parse error on load
- **Cause**: Interrupted write, invalid JSON
- **Solution**: Restore from backup, recreate state
- **Commands**: How to safely reset state

**Issue: State shows wrong panel status**
- **Symptoms**: Panel marked seeded but actually idle
- **Cause**: Crash during update, logic error
- **Solution**: Manual state correction
- **Commands**: How to edit state safely

#### 2.5 Master Orchestrator Problems

**Issue: "No documents found"**
- **Symptoms**: Orchestrator finds no docs to analyze
- **Cause**: Wrong docs path, repo not detected
- **Solution**: Verify paths, check repo detection
- **Commands**: Dry-run to test document collection

**Issue: "Quality validation filtered all prompts"**
- **Symptoms**: No prompts generated, all filtered
- **Cause**: Quality threshold too high, poor source docs
- **Solution**: Adjust threshold, improve source docs
- **Commands**: Check quality scores, review filtering

**Issue: OpenAI API errors**
- **Symptoms**: "API key not found", rate limit errors
- **Cause**: Missing env var, quota exceeded
- **Solution**: Verify API key, check usage
- **Commands**: Test API connectivity

#### 2.6 Performance and Timing Issues

**Issue: Automation is very slow**
- **Symptoms**: Takes >1 minute per panel
- **Cause**: UI waits too long, network delays
- **Solution**: Adjust timing parameters
- **Settings**: Which config to tune

**Issue: Race conditions and random failures**
- **Symptoms**: Works sometimes, fails randomly
- **Cause**: Timing sensitivity, async issues
- **Solution**: Increase wait times, add retries
- **Best practices**: Robust automation patterns

### 3. Debugging Tools and Commands

Document these debugging approaches:

```markdown
### Panel Inspection
# List all detected panels with details
python -m automation.panel_tracker --list

# Dry-run to test panel detection without seeding
python master.py --dry-run

# Check cache state
python -c "from automation.panel_tracker import get_all_chat_panels; print(get_all_chat_panels(use_cache=True))"

### Log Analysis
# View recent automation logs
Get-Content automation/state.json -Tail 50

# Check metrics
python -c "from automation.metrics import get_metrics_tracker; tracker = get_metrics_tracker(); print(tracker.get_summary())"

# Analyze error patterns
python scripts/analyze_logs.py --errors-only

### State Management
# View current panel state
Get-Content automation/panel_state.json | ConvertFrom-Json

# Backup state before changes
Copy-Item automation/panel_state.json automation/panel_state.json.bak

# Reset state (caution!)
Remove-Item automation/panel_state.json

### Test Prompt Generation
# Dry-run orchestrator
python -m automation.master_prompt_orchestrator --dry-run

# Check document collection
python -m automation.master_prompt_orchestrator --dry-run --max-docs 5

# Verify repo detection
python -c "from automation.master_prompt_orchestrator import detect_repo_from_foreground_window; print(detect_repo_from_foreground_window())"
```

### 4. Log Analysis

Teach users how to interpret logs:

```markdown
### Understanding Log Levels
- `DEBUG`: Detailed trace (verbose)
- `INFO`: Normal operation milestones
- `WARNING`: Potential issues (non-fatal)
- `ERROR`: Failures requiring attention
- `CRITICAL`: System-level failures

### Common Log Patterns

**Successful Seeding:**
```
INFO: Found 3 chat panels
INFO: Panel "Task prompt" is IDLE, suitable for seeding
INFO: Successfully seeded panel with prompt index 0
INFO: Selected model: Codex Mini
```

**Failed Seeding:**
```
WARNING: Panel "Task prompt" seeding failed: Could not find input box
ERROR: UI automation error: Element not found
INFO: Panel marked for retry
```

**Detection Issues:**
```
DEBUG: Scanning windows on desktop 0
WARNING: Window handle 12345 is no longer valid
INFO: Refreshed panel cache (3 stale handles removed)
```

### Log File Locations
- Automation state: `automation/state.json`
- Panel state: `automation/panel_state.json`
- Metrics: `automation/metrics.json`
- Cost tracking: `automation/cost_tracker.json`
```

### 5. Advanced Troubleshooting

Cover complex scenarios:

```markdown
### Multi-Desktop Issues
Problem: Panels on inactive desktops not detected
Solution: Force full desktop scan, disable cache

### VS Code Multi-Window Issues
Problem: Automation targets wrong VS Code instance
Solution: Use window title matching, repo detection

### UI Automation Reliability
Problem: Intermittent UI element detection failures
Best Practices:
- Increase wait times in config
- Add retry logic with exponential backoff
- Verify element visibility before interaction
- Use stable element identifiers

### Debugging UI Element Issues
1. Use inspect.exe (Windows SDK) to examine UI structure
2. Verify ControlType and AutomationId
3. Check element hierarchy with debug_dump_controls.py
4. Compare working vs broken panel structures
```

### 6. When to Reset State

```markdown
### Safe State Reset Scenarios
Reset panel state when:
- State file is corrupted (JSON parse error)
- Panel status is clearly wrong (seeded but actually idle)
- Recovering from crash that left inconsistent state

### How to Reset Safely
1. Backup current state: `Copy-Item automation/panel_state.json automation/panel_state.json.bak`
2. Stop all automation: Ensure master.py is not running
3. Remove state: `Remove-Item automation/panel_state.json`
4. Restart automation: State will rebuild from scratch

### What Gets Lost
- Panel seeding history
- Prompt assignment tracking
- Finished panel markers

### What's Preserved
- Prompt files (tasks/generated_prompts/)
- Metrics (metrics.json)
- Cost tracking (cost_tracker.json)
```

### 7. Getting Help

```markdown
### Before Asking for Help

Gather this information:
1. Full error message and stack trace
2. Relevant log excerpts (last 20-30 lines)
3. Panel state JSON (if relevant)
4. Steps to reproduce
5. Environment details (Python version, Windows version, VS Code version)

### Useful Diagnostic Commands
```powershell
# System info
python --version
[Environment]::OSVersion.Version

# Package versions
pip list | Select-String "pywinauto|uiautomation"

# VS Code version
code --version

# Current repo state
git status
git log --oneline -5
```

### Where to Report Issues
- GitHub Issues: [repo URL]
- Include diagnostic output from above
- Attach relevant log files
- Describe expected vs actual behavior
```

## Technical Requirements

### Formatting
- Use Markdown formatting
- Include code blocks with proper syntax highlighting (powershell, python, json)
- Use tables for quick reference information
- Add expandable details sections for verbose output
- Include emojis for visual scanning: ⚠️ Warning, ✅ Success, ❌ Error, 🔍 Debug

### Examples
Every solution must include:
1. Actual command to run (copy-paste ready)
2. Expected output (what success looks like)
3. Example log excerpt (real log format)
4. Common variations of the problem

### Quick Reference
Create a quick reference table at the top:

| Symptom | Likely Cause | Quick Fix | Section |
|---------|--------------|-----------|---------|
| No panels found | VS Code not running | Start VS Code, re-run | [2.1](#panel-detection) |
| Seeding fails | Input box not found | Check panel state | [2.2](#prompt-seeding) |
| ... | ... | ... | ... |

## Success Criteria

### The guide must:
1. ✅ Cover at least 15 distinct issues (5+ per major category)
2. ✅ Include working command examples for each issue
3. ✅ Provide real log excerpts (properly formatted)
4. ✅ Include quick diagnosis flowchart
5. ✅ Be organized with clear table of contents
6. ✅ Use consistent formatting throughout
7. ✅ Be practical (actionable steps, not theory)
8. ✅ Include prevention tips for each issue

### Deliverable:
- Single file: `docs/TROUBLESHOOTING.md`
- Length: 800-1200 lines (comprehensive but not overwhelming)
- No other files modified

## Constraints

### Time Limit
Complete within 2-3 hours of focused work.

### No Scope Creep
- Do NOT create new debugging scripts
- Do NOT modify existing code
- Do NOT add new features
- Do NOT update other documentation files
- Focus purely on troubleshooting existing functionality

### Code Style
- Follow existing docs formatting (see README.md, Architecture.md)
- Use same Markdown conventions
- Match heading structure of other docs

## Reference Files
Review these for common issues:
- `automation/panel_tracker.py` - Panel detection
- `automation/panel_seeding.py` - Seeding logic
- `automation/panel_ui.py` - Model selection
- `automation/panel_state.py` - State management
- `master.py` - Main automation entry point
- `README.md` - For formatting examples

## Example Section

```markdown
## 2.2 Prompt Seeding Failures

### Issue: "Could not find input box"

**Symptoms:**
```
ERROR: Panel seeding failed for "My Task"
ERROR: Could not find input box for panel
WARNING: Panel marked for retry
```

**Cause:**
The UI automation cannot locate the text input element in the Copilot chat panel. This occurs when:
- Panel is in wrong state (not idle)
- UI structure has changed
- Timing issue (element not yet loaded)
- Wrong panel type (not a chat panel)

**Solution:**
1. Verify panel state:
   ```powershell
   python -c "from automation.panel_state import load_panel_state; print(load_panel_state())"
   ```

2. Check if panel is actually idle:
   ```powershell
   python master.py --dry-run
   # Look for panel classification in output
   ```

3. If panel is mis-classified, reset state:
   ```powershell
   # Backup first
   Copy-Item automation/panel_state.json automation/panel_state.json.bak
   # Edit state.json to mark panel as IDLE
   ```

4. Retry seeding with fresh state

**Prevention:**
- Ensure panels are completely idle before seeding
- Wait for VS Code UI to fully load
- Avoid seeding panels that are actively processing

**Related Issues:**
- See [2.1 Panel Detection](#panel-detection) if panel not found at all
- See [2.3 Model Selection](#model-selection) if seeding works but model selection fails
```

## Final Checklist
Before submitting:
- [ ] All 15+ issues documented
- [ ] Every issue has: symptoms, cause, solution, prevention
- [ ] All commands tested and working
- [ ] Log excerpts are realistic
- [ ] Quick reference table complete
- [ ] TOC links work
- [ ] Formatting is consistent
- [ ] No code modifications (doc only)

---
**Agent Assignment**: Grok (simple documentation task, clear structure, well-defined scope)
**Estimated Time**: 2-3 hours
**Priority**: High (frequently requested by users)
**Dependencies**: None
