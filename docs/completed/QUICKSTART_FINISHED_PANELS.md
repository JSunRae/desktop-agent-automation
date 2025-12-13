# Quick Start Guide - Finished Panel Follow-Through

## 🚀 Quick Test (Dry-Run)

```powershell
# 1. Set environment variables
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:FINISHED_PANEL_DRY_RUN = "true"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# 2. Run orchestrator
python -m automation.orchestrator

# 3. Watch for dry-run messages
# Look for: "[PanelTracker][DRY-RUN] Would keep edits, open new chat..."
```

## ⚡ Quick Test (Live Mode)

```powershell
# 1. Set environment variables
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:FINISHED_PANEL_DRY_RUN = "false"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# 2. Run orchestrator
python -m automation.orchestrator

# 3. Watch the test panel for real actions
# Panel should: Keep Edits → New Chat → Select Model → Paste Prompt
```

## 🔧 Quick Commands

```powershell
# Run unit tests
python -m pytest tests/test_finished_panel_followups.py -v

# Run dry-run test script
python scripts\test_dry_run.py

# Disable feature
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "false"

# View panel state
Get-Content automation\panel_state.json | Select-Object -First 50

# Check prompt file
Get-Content tasks\generated_prompts\latest.txt
```

## 📋 Checklist Before Going Live

- [ ] Dry-run test passed
- [ ] Test prompt file exists (`tasks/generated_prompts/latest.txt`)
- [ ] Test panel ready ("Testing window functionality - desktop-agent-automation")
- [ ] Monitoring logs for first 10 minutes
- [ ] Ready to press Ctrl+C if needed

## 🔍 What to Watch For

### Success Indicators ✅
- `[PanelTracker][DRY-RUN]` messages in dry-run
- Panel actions occurring smoothly in live mode
- Prompt appears in chat input box
- Model correctly selected based on prompt header
- Panel marked as RUNNING and seeded

### Warning Signs ⚠️
- Multiple attempts on same panel
- Model picker not found errors
- New Chat doesn't open
- Prompt not pasted correctly
- Unintended panels being processed

## 📞 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| No panels processed | Check if panels are in FINISHED state and unseeded |
| Model picker not found | Verify button name: "Pick Model (Ctrl+Alt+.)" |
| Prompt file not found | Create `tasks/generated_prompts/latest.txt` |
| Permission denied | Ensure `ENABLE_SEND_TO_INACTIVE_PANELS=true` |
| Wrong panel processed | Check panel title matches exactly |

## 📚 Key Documentation

- **Full Handover**: `HANDOVER.md`
- **Validation Report**: `docs/completed/HANDOVER_VALIDATION.md`
- **Environment Variables**: `docs/ENVIRONMENT_VARIABLES.md`
- **Model Picker Dependencies**: See `ENVIRONMENT_VARIABLES.md` → "Model Picker UI Dependencies" section
- **Task Tracking**: `docs/Todo.md`
- **Configuration**: `automation/config.py`

## 🎯 Test Panel Setup

1. Open VS Code with Copilot
2. Name panel: "Testing window functionality - desktop-agent-automation"
3. Let agent finish or manually stop
4. Wait 30+ minutes or manually mark as finished
5. Run orchestrator

## 💾 Important Files

```
automation/
  ├── config.py                    # Configuration
  ├── orchestrator.py              # Main loop
  ├── panel_tracker.py             # Core logic
  ├── panel_state.json            # Persisted state
  └── master_prompt_orchestrator.py  # System prompt

tasks/
  └── generated_prompts/
      └── latest.txt              # Prompt batch

tests/
  └── test_finished_panel_followups.py  # Unit tests

scripts/
  └── test_dry_run.py             # Dry-run test
```

## 🛑 Emergency Stop

```powershell
# Press Ctrl+C in terminal
# OR disable feature
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "false"
```

---
*Quick reference - December 7, 2025*
