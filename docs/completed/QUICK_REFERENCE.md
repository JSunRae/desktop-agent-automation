# Quick Reference - New Features (December 7, 2025)

## 🚀 Quick Commands

### Validate Live Mode Prerequisites
```powershell
python scripts\validate_live_test.py
```
Checks if all prerequisites are met before running live mode.

### Analyze Logs for Issues
```powershell
# Last hour
python scripts\analyze_logs.py

# Last 6 hours
python scripts\analyze_logs.py --hours 6

# Custom log file
python scripts\analyze_logs.py --log-file path\to\log.txt --hours 12
```
Detects false positives, errors, warnings, and suspicious patterns.

### View Metrics
```powershell
python scripts\view_metrics.py
```
Shows:
- Prompt seeding success rates
- Model usage distribution
- Prompt distribution (round-robin)
- Recent events

### Run Tests
```powershell
# All new tests
python -m pytest tests/test_finished_panel_followups.py tests/test_round_robin_prompts.py tests/test_metrics.py -v

# Individual test suites
python -m pytest tests/test_round_robin_prompts.py -v
python -m pytest tests/test_metrics.py -v
python tests\test_repo_detection.py
```

## 🎯 Key Features

### 1. Round-Robin Prompt Queue
**What:** Prompts are now assigned in sequence instead of always using the first prompt.

**How it works:**
- Panel 1 gets Prompt 0
- Panel 2 gets Prompt 1
- Panel 3 gets Prompt 2
- Panel 4 gets Prompt 3
- Panel 5 gets Prompt 0 (wraps around)

**State:** Persisted in `automation/panel_state.json`

**Field:** `assigned_prompt_index` on each panel

### 2. Repo Detection from Foreground Window
**What:** Automatically detects which repo you're working on from VS Code window title.

**Format:** `"[file] - [repo-name] - Visual Studio Code"`

**Search paths:**
- Windows: `C:/Users/{user}/Documents/Vs Code Projects/{repo}/docs`
- WSL: `//wsl.localhost/{distro}/home/{user}/{projects}/{repo}/docs`

**Integration:** Automatically used by master orchestrator when generating prompts.

### 3. Metrics Tracking
**What:** Comprehensive tracking of prompt seeding and model selection events.

**Tracked data:**
- Timestamp of each event
- Panel title
- Prompt index
- Model requested
- Success/failure
- Error messages

**Storage:** `automation/metrics.json`

**Access:** Use `scripts/view_metrics.py` to view summary

### 4. Log Analysis
**What:** Automated log analysis to detect issues and false positives.

**Detects:**
- Errors and warnings
- Seeding attempts
- Rate limit events
- Panel state changes
- Suspicious patterns (user text issues, operation failures)

**Output:** Categorized summary with recent events

### 5. Live Mode Validation
**What:** Pre-flight check before running in live mode.

**Checks:**
- Prompt file exists and is valid
- Environment variables correctly set
- Feature flags enabled

**Provides:** Clear instructions for enabling live mode safely

## 📊 Data Structures

### Panel State (Enhanced)
```python
{
  "window_title": "...",
  "seeded_prompt": true,
  "assigned_prompt_index": 2,  # NEW: Which prompt was assigned
  ...
}
```

### Panel Tracker (Enhanced)
```python
{
  "next_prompt_index": 5,  # NEW: Round-robin counter
  "panels": { ... }
}
```

### Metrics
```json
{
  "last_updated": "2025-12-07T...",
  "prompt_metrics": [
    {
      "timestamp": "...",
      "panel_title": "...",
      "prompt_index": 0,
      "prompt_preview": "...",
      "model_requested": "GPT-5.1-Codex-Max (Preview)",
      "success": true,
      "error_message": null
    }
  ],
  "model_metrics": [
    {
      "timestamp": "...",
      "panel_title": "...",
      "model_label": "GPT-5.1 Codex",
      "success": true
    }
  ]
}
```

## 🔧 Configuration

All features use existing environment variables:
- `ENABLE_FINISHED_PANEL_FOLLOWUPS` - Enable finished panel processing
- `FINISHED_PANEL_DRY_RUN` - Dry-run mode (safe testing)
- `ENABLE_SEND_TO_INACTIVE_PANELS` - Allow sending to inactive panels
- `FINISHED_PANEL_PROMPT_PATH` - Path to prompt file (default: `tasks/generated_prompts/latest.txt`)

## 📁 New Files

**Scripts:**
- `scripts/validate_live_test.py` - Live mode validation
- `scripts/analyze_logs.py` - Log analysis tool
- `scripts/view_metrics.py` - Metrics viewer

**Tests:**
- `tests/test_round_robin_prompts.py` - Round-robin tests
- `tests/test_repo_detection.py` - Repo detection tests
- `tests/test_metrics.py` - Metrics tracking tests

**Modules:**
- `automation/metrics.py` - Metrics tracking system

**Documentation:**
- `docs/completed/COMPLETION_SUMMARY_2025-12-07.md` - Detailed summary of completed work

## 💡 Tips

1. **Always validate before live mode:**
   ```powershell
   python scripts\validate_live_test.py
   ```

2. **Monitor metrics regularly:**
   ```powershell
   python scripts\view_metrics.py
   ```

3. **Check logs for issues:**
   ```powershell
   python scripts\analyze_logs.py --hours 6
   ```

4. **Verify round-robin is working:**
   Check `assigned_prompt_index` in `automation/panel_state.json`

5. **Test repo detection:**
   ```powershell
   python tests\test_repo_detection.py
   ```

## 🚦 Status

All 6 high-priority tasks complete:
- ✅ Finished panel validation
- ✅ Live mode testing infrastructure
- ✅ Log monitoring
- ✅ Round-robin prompt queue
- ✅ Repo detection
- ✅ Metrics tracking

All tests passing: **7/7** ✅

---
*Last updated: December 7, 2025*
