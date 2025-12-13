# Todo - Desktop Agent Automation

## Current Status
This is a living document tracking all open tasks, blockers, and priorities for the desktop agent automation system.

## High Priority Tasks

### Feature Enhancements
- [x] API call to classify idle panel output before seeding
- [ ] Handle "OK" button after Keep Edits if confirmation needed
- [x] Add retry logic if New Chat fails to open
- [x] Better error recovery for failed seeding attempts

### Documentation
- [x] Document model picker UI dependencies
- [ ] Create troubleshooting guide for common failures
- [ ] Refresh cost-tracker pricing tables + `.env` overrides whenever OpenAI updates rates (monthly check via `python scripts/verify_pricing.py` + follow-up PR)

## Recurring Reminders
- [ ] First business day of every month: run `python scripts/verify_pricing.py --json`, review diffs against `DEFAULT_MODEL_RATES`, and commit any adjustments with notes in `logs/pricing_checks/`.

## Medium Priority

### Advanced Features
- [ ] Multi-repo support with separate prompt batches
- [ ] Agent assignment tracking (which prompt → which panel)
- [ ] Feedback loop to parse agent responses
- [ ] Cost tracking for OpenAI spend

### Code Quality
- [ ] Add comprehensive error handling throughout

## Roadmap Items

### Immediate (High Priority)
- [ ] Validate dry-run on real test panel ("Testing window functionality - desktop-agent-automation") - Depends on: test panel setup, dry-run mode enabled
- [ ] Test live mode on same panel with a benign prompt - Depends on: dry-run validation, safety flags enabled
- [ ] Monitor logs for 5-10 minutes to ensure no false positives - Depends on: logging system active

### Short-term (Medium Priority)
- [ ] Implement prompt queue/round-robin instead of always first prompt - Depends on: prompt file parsing, panel state tracking
- [ ] Add repo-root detection from foreground VS Code window title (parse for repo name) - Depends on: window title parsing, workspace detection
- [ ] Create `docs/Todo.md` stub in both repos (currently missing) - Depends on: repo detection, file creation
- [ ] Add metrics: track seeded prompts, model selections, success rates - Depends on: metrics.py, panel state updates

### Medium-term (Low Priority)
- [ ] Handle "OK" button after Keep Edits if agent wants confirmation - Depends on: UI element detection, confirmation dialog handling
- [ ] Retry logic if New Chat fails to open or model picker not found - Depends on: error handling, UI interaction retries
- [ ] Better error recovery: if seeding fails, mark panel as needing retry instead of seeded - Depends on: panel state management, error classification

### Advanced (Future)
- [ ] Multi-repo support: maintain separate prompt batches per repo - Depends on: repo detection, prompt batch management
- [ ] Agent assignment tracking: which prompt was sent to which panel - Depends on: panel state, prompt metadata
- [ ] Feedback loop: parse agent response to auto-mark as completed or adjust next prompt - Depends on: response parsing, task status updates
- [ ] Cost tracking: estimate OpenAI spend from seeded prompts + agent runs - Depends on: cost_tracker.py, API usage metrics

## Completed Tasks

### Recent Completions (December 8, 2025)
- [x] Fix window scanning on inactive desktops when using cache
- [x] Update README.md with finished-panel follow-through section
- [x] Deepen quick panel detection depth so Allow dialogs classify as live
- [x] Always sweep idle windows to catch stray Allow dialogs after live passes
- [x] Reacquire cached window handles after desktop switches to click Trading allows reliably
- [x] Add environment variable reference table
- [x] Fix type errors in panel_tracker.py (uiautomation stubs)
- [x] Refactor duplicated code across modules (logging utils)

### Recent Completions (December 7, 2025)
- [x] Validate finished panel follow-through on real test panel
- [x] Test live mode with benign prompt
- [x] Monitor logs for false positives
- [x] Implement prompt queue/round-robin
- [x] Add repo-root detection from foreground VS Code window title
- [x] Add metrics tracking for seeded prompts and model selections

### Previous Completions
- [x] Implement finished panel detection
- [x] Add dry-run mode for safe testing
- [x] Create unit tests for finished panel followups
- [x] Update system prompt for master orchestrator
- [x] Add workspace detection for docs folders
- [x] Implement model selection logic (Grok/Codex Mini/Codex/Codex Max)
- [x] Validate finished panel follow-through with validation infrastructure
- [x] Create live mode testing prerequisites checker
- [x] Implement log analysis tool for false positive detection
- [x] Implement comprehensive metrics tracking for prompts and models

## Blocked Items
None currently.

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
- Test panel name: "Testing window functionality - desktop-agent-automation"
- Prompt file location: `tasks/generated_prompts/latest.txt`
- Panel state persisted in: `automation/panel_state.json`

---
*Last updated: December 11, 2025*
