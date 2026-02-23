# desktop-agent-automation

## Overview
- Automates clicking "Allow", "Keep Edits", and "Try Again" buttons in VS Code Copilot.
- Supports multi-desktop scanning and automatic window switching.
- **NEW**: Desktop Auto-Allow Agent using OpenAI Computer Use API to automatically detect and click Copilot approval buttons.
- **NEW**: Automatic master-agent prompts – when no "Allow" happens for an hour, the workspace docs from WSL are uploaded to OpenAI and a fresh pack of 10 coordinated prompts is generated in `tasks/generated_prompts/`.
- **NEW**: Cost tracking for OpenAI API usage across all agents.
- **NEW**: Comprehensive metrics tracking for prompt seeding, model selections, and success rates.
- **NEW**: Round-robin prompt assignment to distribute work evenly across panels.
- **NEW**: Repository detection from VS Code window titles for automatic docs discovery.
- **NEW**: Feedback loop system that parses agent responses to improve future prompt generation and avoid problematic prompts.
- **NEW**: Panel transcript quality dashboard with automated scoring, flagging, and weekly trend reports.
- **NEW**: Library-friendly `MasterPromptOrchestrator` API with `refresh_all_feeds()`.

### Master Prompt Orchestrator (Library Usage)

You can run the prompt refresh workflow directly in Python without CLI arguments:

```python
from automation.master_prompt_orchestrator import MasterPromptOrchestrator

orchestrator = MasterPromptOrchestrator()
orchestrator.refresh_all_feeds()
```

To avoid re-discovery when you already know the repos, pass `repo_configs` and set `force_discovery=False`:

```python
from automation.master_prompt_orchestrator import MasterPromptOrchestrator, RepoConfig
from pathlib import Path

orchestrator = MasterPromptOrchestrator(
    repo_configs=[RepoConfig(name="default", docs_dirs=[Path("docs")])]
)
orchestrator.refresh_all_feeds(force_discovery=False)
```

## Panel Quality Dashboard & Reports

The automation continuously samples transcript snapshots from every Copilot panel and scores them for completeness, test health, documentation quality, and alignment with the original prompt. Each assessment is stored alongside the panel in `automation/panel_state.json`, allowing you to track whether a conversation is **COMPLETED**, **IN_PROGRESS**, **NEEDS_REVISION**, or **BLOCKED**.

Key capabilities:

- Pattern detection for TODO markers, placeholder code, merge conflicts, failing tests, and runtime errors.
- Automatic flags for agent confusion, repeated failures, degraded output quality, and missing documentation.
- Quality metrics feed back into the feedback analyzer to influence future prompt selection and filtering.
- Weekly trend reports highlight completion rates, top recurring issues, and recommended remediation steps.

Use the CLI dashboard to review the current state across all panels:

```powershell
# Render a formatted dashboard with the top panels that need review
python scripts/panel_quality_dashboard.py

# Emit raw JSON plus persist the latest weekly trend report
python scripts/panel_quality_dashboard.py --json --weekly-report
```

Weekly reports are written to `automation/quality_reports/quality_report_YYYY_MM_DD.json` and include status counts, average quality scores, quality alerts, and actionable recommendations. The dashboard pulls from the same data to surface panels that require human review so you can intervene before quality regresses.

## Quick Start (Launcher)
- **Launcher:** `master`
- **Fallback:** `./scripts/ml_master.sh`

1. Activate your virtual environment and run `pip install -e .[dev]` to register the console script.
2. **WSL/Linux:** expose the launcher globally with `ln -sf "$PWD/master" ~/.local/bin/master` so any shell can reach it.
3. **Windows shells:** either add `.<repo>\.venv\Scripts` to `PATH` or copy `master.cmd` into `%LOCALAPPDATA%\Microsoft\WindowsApps`.
4. Optional: keep the fallback script handy (`TF1_LIST_TOOLS=1 ./scripts/ml_master.sh`) to list tools even if the console script cannot be regenerated immediately.

## Master Launcher

The `master` command provides a unified interface to all automation workflows and utilities:

```powershell
# List all available commands
master --list

# Run a specific workflow by key
master --run desktop-auto-allow

# Dry run to see what command would be executed
master --dry-run --run align-panels

# Get JSON metadata for external tools
master --describe
```

Available workflows include:
- **run-automation**: Main hotkey + panel automation orchestrator
- **desktop-auto-allow**: Computer-Use API agent for clicking approval buttons
- **vs-code-automation**: Primary VS Code chat automation with hotkeys
- **master-prompt-orchestrator**: Idle supervisor for generating prompt batches
- **align-panels**: Panel alignment utility
- **prompt-tester**: Validation tool for new prompt packs
- And various test suites for different components

---

## Installation
```powershell
pip install -r requirements.txt
```

### Developer install (recommended)

For running tests and lint/format tooling locally:

```powershell
pip install -e ".[dev]"
```

You can also mirror CI with the curated files:

```powershell
pip install -r requirements-dev.txt -c constraints-dev.txt
```

## Standard Automation (Modular)

The primary UI-based automation loop. It scans VS Code windows across all virtual desktops and automatically clicks "Allow", "Keep Edits", and "Try Again" buttons.

### Running the Automation
```powershell
python run_automation.py
```

### Autonomous Task Discovery (optional)
Run the automation with background prompt auditing and Todo ingestion:

```powershell
python run_automation.py --autonomous
```

Configure the daemon cadence in `.env` or `automation/config.py`:
- `TASK_DISCOVERY_INTERVAL_SECONDS` (default: 900)
- `TASK_DISCOVERY_LOW_TASK_THRESHOLD` (default: 2)

### Configuration
Edit `automation/config.py` or set environment variables in `.env` to customize:
- `DESKTOPS_TO_CHECK`: List of virtual desktop names to scan.
- `MAX_ALLOWS_PER_HOUR`: Rate limiting threshold.
- `COOLDOWN_MINUTES`: Wait time after hitting a rate limit.

### Features
- **Multi-Desktop Support**: Automatically switches between virtual desktops to find active VS Code windows.
- **Rate Limit Management**: Tracks "Allow" clicks and "Try Again" buttons to avoid hitting Copilot's rate limits.
- **Smart Window Detection**: Identifies VS Code windows by title and focuses them before clicking.
- **Safety Guard**: Detects manual mouse movement and pauses automation to avoid fighting the user.

---

## Panel Alignment Utility

### Overview
Windows often moves VS Code windows around due to DPI scaling issues (VS Code is not DPI-aware per monitor like native WinUI apps). This causes your carefully arranged panels to clump together in the middle of your screens. The panel alignment script helps fix this automatically.

### Quick Start

**First time - Configure your layout:**
```powershell
# Arrange your windows exactly how you want them, then:
python scripts/align_panels.py --configure

# Or for a specific desktop:
python scripts/align_panels.py --configure --desktop TF
```

**Realign panels when Windows moves them:**
```powershell
# Realign on current desktop
python scripts/align_panels.py

# Realign on specific desktop
python scripts/align_panels.py --desktop TF

# Preview changes without applying
python scripts/align_panels.py --dry-run
```

### Features
- **Pattern Matching**: Identifies windows by title patterns (e.g., "Priority: P1", "tf_1", "Trading")
- **Multi-Monitor Support**: Works with multiple monitors, storing positions relative to each monitor
- **Desktop-Specific Layouts**: Different configurations for different virtual desktops
- **Safe Testing**: Dry-run mode to preview changes before applying
- **Interactive Configuration**: Captures current window positions with guided prompts

### Common Use Cases

**Two-column layout** (Priority 1 and 2 side-by-side):
```powershell
python scripts/align_panels.py --configure --desktop TF
# Then whenever Windows moves them:
python scripts/align_panels.py --desktop TF
```

**Multi-monitor setup** (different panels on different screens):
```powershell
python scripts/align_panels.py --configure --desktop Trading
```

**Multiple layouts** (morning vs evening setups):
```powershell
python scripts/align_panels.py --configure --config-name morning
python scripts/align_panels.py --configure --config-name evening
# Switch between them:
python scripts/align_panels.py --config-name morning
```

See [docs/PANEL_ALIGNMENT.md](docs/PANEL_ALIGNMENT.md) for detailed documentation and examples.

---

## Desktop Auto-Allow Agent (OpenAI Computer Use)

### Overview
The Desktop Auto-Allow Agent uses OpenAI's Computer Use API with vision capabilities to:
- Automatically detect GitHub Copilot Agent approval buttons ("Allow", "Continue", "Apply", etc.)
- Click them without manual intervention
- Handle rate limiting with automatic 20-minute cooldowns
- Run continuously in the background while your sub-agents work

### Prerequisites
1. **OpenAI API Key** with access to vision-capable models (GPT-4o or computer-use-preview when available)
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

### Configuration
Set your OpenAI API key as an environment variable:
```powershell
$env:OPENAI_API_KEY = "sk-your-api-key-here"
```

To persist the key across sessions, add it to your PowerShell profile:
```powershell
[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-your-api-key-here', 'User')
```

### Running the Agent

#### Continuous Mode (Recommended)
Run the agent in a loop with default settings (checks every 60 seconds):
```powershell
python -m automation.desktop_auto_allow_agent
```

#### Custom Interval
Check every 30 seconds instead of 60:
```powershell
python -m automation.desktop_auto_allow_agent --interval 30
```

#### Dry Run Mode (Testing)
See what the agent would do without actually clicking:
```powershell
python -m automation.desktop_auto_allow_agent --dry-run
```

#### One-Time Check
Run once and exit (useful for testing):
```powershell
python -m automation.desktop_auto_allow_agent --once
```

### How It Works
1. Every 60 seconds (or custom interval), the agent:
   - Captures a screenshot of your desktop
   - Sends it to OpenAI with a specialized system prompt
   - Receives one of three responses:
     - `STATUS: CLICKED` - Found and clicked an approval button
     - `STATUS: NO_BUTTON` - No approval button detected
     - `STATUS: RATE_LIMITED` - Detected Copilot rate limiting
2. If rate limited, the agent automatically waits 20 minutes before checking again
3. All activity is logged to `automation/auto_allow.log`

### Safety Features
The agent is designed with multiple safety measures:
- Only clicks buttons that match GitHub Copilot Agent approval patterns
- Never clicks window controls, taskbar, or system UI
- Never types text or uses keyboard shortcuts
- Conservative approach: when in doubt, it does nothing
- Dry-run mode for testing before enabling real clicks

### Typical Workflow
1. Start your Copilot sub-agent tasks (manually or with the hotkey automation)
2. In a separate terminal, start the Desktop Auto-Allow Agent:
   ```powershell
   python -m automation.desktop_auto_allow_agent
   ```
3. The agent runs in the background, automatically clicking "Allow" when needed
4. Monitor `automation/auto_allow.log` to see agent activity
5. Press Ctrl+C to stop the agent when done

### Troubleshooting
- **"OpenAI API key required"**: Set the `OPENAI_API_KEY` environment variable
- **Import errors**: Run `pip install -r requirements.txt`
- **Agent not clicking**: Check the log file for status messages. Try `--dry-run --once` to see what it detects
- **Too many API calls**: Increase `--interval` to reduce frequency (e.g., `--interval 120` for 2-minute checks)

## Master Prompt Orchestrator (idle supervisor)

When Copilot hasn't shown an `Allow` button for 60 minutes (after at least one successful Allow in the session), the script now promotes itself to a "master agent":

1. Pulls the latest docs from configured repository paths (supports multiple repos with separate prompt batches discovered via env, cross-repo snapshots, or legacy fallbacks).
2. Uploads concise slices of up to 18 recently modified text files (3.5k chars each) per repo to OpenAI and asks for **exactly 10** independent prompts that include a recommended model (Grok, Sonnet 4.5, or GPT 5.1 codex mini) plus instructions to update Todos, task assignments, README, Architecture, and the originating doc.
3. Stores separate prompt batches as `tasks/generated_prompts/{repo_name}/master_prompts_<timestamp>.txt` and mirrors to `tasks/generated_prompts/{repo_name}/latest.txt` for easy access. A JSONL manifest is maintained for each repo.

**Multi-Repo Support**: Configure multiple repositories with `MASTER_AGENT_REPO_CONFIGS` or `--repos`, or rely on the cross-repo Todo snapshot for automatic discovery. Each repo gets its own isolated prompt batch under `tasks/generated_prompts/<repo>/` to prevent context mixing.

See `docs/multi_repo_prompt_batches.md` for a detailed walkthrough of discovery order, environment overrides, and dispatcher routing.

Environment knobs (all optional):

- `NO_ALLOW_TRIGGER_MINUTES` – minutes of inactivity before triggering (default 60).
- `PROMPT_GENERATION_COOLDOWN_MINUTES` – cooldown between prompt batches (default 90 minutes).
- `MASTER_AGENT_DOCS_ROOT`, `MASTER_AGENT_OPEN_TASKS_ROOT` – UNC paths to scan (single repo mode).
- `MASTER_AGENT_REPO_CONFIGS` – JSON array defining multiple repos with their doc paths.
- `MASTER_AGENT_MAX_DOCS`, `MASTER_AGENT_MAX_CHARS` – cap volume sent to OpenAI.
- `MASTER_AGENT_PROMPT_DIR` – change the output folder if you want to feed another automation loop.

Use the prompts however you like: open 10 new Copilot chats manually, or use the automated prompt seeding tools. Each prompt already reminds the sub-agent to update the CLI, Todos, README, Architecture, and the source doc it came from so you keep state in sync.

---

## Cost Tracking & Metrics

### Cost Tracking
The system provides comprehensive OpenAI API cost tracking to prevent unexpected bills:

- **All API calls tracked**: Vision, text completions, and computer use APIs
- **Real-time monitoring**: Live cost updates with session totals
- **Budget management**: Configurable daily/weekly/monthly limits with alerts
- **Detailed reporting**: Cost breakdowns by model, feature, and time period
- **Cost estimation**: Dry-run cost calculation for planning
- **Integration**: Cost data integrated with automation metrics

### Viewing Cost Reports
```powershell
# Comprehensive cost report (last 7 days)
python scripts/cost_report.py

# Cost report for last 30 days
python scripts/cost_report.py --days 30

# Group costs by model instead of day
python scripts/cost_report.py --group-by model

# Show only budget alerts
python scripts/cost_report.py --alerts-only

# View all metrics including costs
python scripts/view_metrics.py
```

### Cost Configuration
Configure budgets and rates via environment variables:
```powershell
# Budget limits (USD)
$env:COST_TRACKER_DAILY_LIMIT = "10.0"
$env:COST_TRACKER_WEEKLY_LIMIT = "50.0" 
$env:COST_TRACKER_MONTHLY_LIMIT = "200.0"

# Model rates override
$env:COST_TRACKER_MODEL_RATES = '{"gpt-4o": {"input_per_1k": 0.001, "output_per_1k": 0.002}}'

# Vision cost per image
$env:COST_TRACKER_VISION_COST_PER_IMAGE = "0.02"
```

#### `COST_TRACKER_MODEL_RATES` (Approximate Defaults)

If `COST_TRACKER_MODEL_RATES` is **not** set, the tracker falls back to approximate OpenAI pricing so it can still provide directional estimates. These placeholders are intentionally conservative and should be overridden with the rates from your current OpenAI billing plan.

| Model        | Input $/1k tokens | Output $/1k tokens |
|--------------|-------------------|--------------------|
| `gpt-4o-mini` | 0.00045           | 0.00090            |
| `gpt-4o`      | 0.00100           | 0.00200            |
| `gpt-4-turbo` | 0.00100           | 0.00200            |

Update the environment variable with a JSON object keyed by model name (case-insensitive). Example with multiple entries:

```powershell
$env:COST_TRACKER_MODEL_RATES = '{
    "gpt-4o": {"input_per_1k": 0.00075, "output_per_1k": 0.0028},
    "gpt-4o-mini": {"input_per_1k": 0.00025, "output_per_1k": 0.0006}
}'
```

> **Approximate only:** Leave the variable unset *only* if you accept these placeholder rates. For accurate budget alerts and reports, set `COST_TRACKER_MODEL_RATES` explicitly.

### Metrics Tracking
Comprehensive metrics collection for monitoring system performance:

- **Prompt seeding metrics**: Tracks which prompts were sent to which panels, success/failure rates
- **Model selection metrics**: Records which AI models were requested for each task
- **Panel processing statistics**: Success rates, error messages, timing data
- **Cost snapshots**: Historical cost data integrated with metrics
- **Persistence**: All metrics saved to `automation/metrics.json`

### Unified Telemetry Dashboard & Reports
`scripts/generate_metrics_report.py` unifies every telemetry source (`automation/metrics.json`, `automation/assignment_metrics.jsonl`, `automation/allow_metrics.jsonl`, `automation/panel_state.json`, `logs/cost_metrics.jsonl`, and related trackers) into live dashboards and exportable analytics.

```powershell
# Live dashboard with continuous refresh, anomaly alerts, and ASCII charts
master --run metrics-dashboard

# Generate consolidated JSON + Markdown summaries (written to logs/metrics_reports/)
master --run metrics-export
```

Key capabilities:
- Panel seeding trend analysis with slopes, ASCII sparklines, and success/failure counts.
- Model mix + effectiveness plus round-robin fairness scoring so prompt slots stay balanced.
- Repository heatmaps that highlight hot hours per repo, desktop switching reliability, and allow-button health.
- Agent productivity analytics (tasks/hour, average task duration, active panels) and error-rate trend tracking by category.
- Cost-efficiency metrics (cost per completion, spike detection) blended with Copilot budget alerts.
- Real-time anomaly detection using rolling baselines stored in `logs/metrics_reports/history.jsonl`.
- Automatic retention policies (default 30 days) and daily/weekly/monthly summaries saved to `logs/metrics_reports/`.

Advanced CLI flags:

```powershell
# Customize refresh cadence or history storage location
python scripts/generate_metrics_report.py --mode dashboard --refresh-seconds 8 --history-path logs/metrics_reports/history.jsonl

# Export to a custom folder and extend retention/baseline windows
python scripts/generate_metrics_report.py --mode export \
    --export-json c:/data/metrics/latest.json \
    --export-markdown c:/data/metrics/latest.md \
    --retention-days 90 --baseline-days 21
```

All outputs default to `logs/metrics_reports/` and stay ASCII-friendly for terminal viewing.

### Rate-limit telemetry

Every five minutes the script writes a JSON line to `automation/allow_metrics.jsonl` containing:

- `allows_last_window` – number of `Allow` clicks in the past hour.
- `panels_last_window` – unique VS Code windows (panels) that clicked Allow in that hour.
- Per-loop counts for `Allow` vs `Keep All Edits` clicks plus the configured polling interval.

This log is the foundation for a future adaptive-rate algorithm: by plotting allows/hour vs rate-limit events you can dial in the fastest safe pace.

---

## Panel State Detection & Input Reading

### Overview
The automation can detect and read from VS Code Copilot panels using Windows UI Automation:

- **Panel State Detection**: Determine if a panel is RUNNING (agent working) or IDLE (ready for input)
- **Input Text Reading**: Read text that's been typed in the chat input box before sending
- **Safe Text Sending**: Only send automated prompts to panels without user-prepared text

### Panel State Detection

Panels are identified by which button is visible:
- **Cancel button** (`Cancel (Alt+Backspace)`) → Panel is **RUNNING** (agent actively working)
- **Send button** → Panel is **IDLE** (ready for input or finished)

```python
import uiautomation as auto
from automation.panel_tracker import detect_panel_running_state, get_comprehensive_panel_state

# Find VS Code window
vs_win = auto.WindowControl(searchDepth=1, SubName="Visual Studio Code")

# Simple check: is it running?
is_running = detect_panel_running_state(vs_win)  # True = Cancel visible, False = Send visible

# Comprehensive check: get detailed state
state = get_comprehensive_panel_state(vs_win)
# Returns: {
#   "is_running": bool,
#   "has_chat_panel": bool,
#   "has_send_button": bool,
#   "idle_reason": IdleReason or None,
#   "needs_action": bool
# }
```

### Reading Input Text from Chat Box

The chat input box uses Monaco editor which doesn't expose text via standard ValuePattern. To read the input text, use the **clipboard method**:

1. Focus the VS Code window
2. Press `Escape` to dismiss any dialogs
3. Press `Ctrl+L` to focus the chat input
4. Press `Ctrl+A` to select all text
5. Press `Ctrl+C` to copy to clipboard
6. Read from clipboard

```python
import uiautomation as auto
import pyperclip
import time

def read_chat_input(vs_win):
    """Read text from the chat input box via clipboard."""
    try:
        # Clear clipboard
        pyperclip.copy("")
        
        # Focus window
        vs_win.SetFocus()
        time.sleep(0.3)
        
        # Dismiss any dialogs
        auto.SendKeys("{Escape}")
        time.sleep(0.3)
        
        # Focus chat input
        auto.SendKeys("{Ctrl}l")
        time.sleep(0.2)
        
        # Select all and copy
        auto.SendKeys("{Ctrl}a")
        time.sleep(0.1)
        auto.SendKeys("{Ctrl}c")
        time.sleep(0.2)
        
        # Get clipboard content
        content = pyperclip.paste()
        return content.strip() if content else ""
        
    except Exception as e:
        return f"Error: {e}"

# Usage
vs_win = auto.WindowControl(searchDepth=1, SubName="Visual Studio Code")
input_text = read_chat_input(vs_win)
print(f"Current input: {input_text}")
```

### Key Findings

1. **ValuePattern doesn't work** for Monaco editor - the input box doesn't expose its text through standard UI Automation patterns
2. **Focus is required** - the text input must be focused before it can be read
3. **Ctrl+L focuses chat** - this VS Code shortcut reliably focuses the Copilot chat input
4. **Clipboard is reliable** - using Ctrl+A/Ctrl+C and reading clipboard works consistently
5. **Dialogs interfere** - "Start new chat?" dialogs can capture focus; use Escape first

### Safe Text Sending

The automation tracks panels that have user-prepared text and skips them:

```python
from automation.panel_tracker import send_text_to_chat

# This will:
# 1. Check if the panel has existing text
# 2. If yes, skip and remember this panel for the rest of the run
# 3. If no, send the text and press Enter
success = send_text_to_chat(vs_win, "please continue")
```

---

### Cost Considerations
- Each check sends a screenshot to OpenAI's vision API
- At 60-second intervals, that's ~60 API calls per hour
- Monitor your OpenAI usage dashboard and adjust `--interval` as needed
- Consider using `--once` mode triggered by hotkeys for manual control

---

## Documentation & Troubleshooting

For detailed documentation on specific features:

- **[Environment Variables](docs/ENVIRONMENT_VARIABLES.md)**: Complete guide to all configuration options
- **[Troubleshooting](docs/TROUBLESHOOTING.md)**: Common issues and solutions
- **[Architecture](docs/ARCHITECTURE.md)**: System design and component interactions
- **[Panel Alignment](docs/PANEL_ALIGNMENT.md)**: Detailed panel positioning guide
- **[Cost Tracking](docs/COST_TRACKING.md)**: Advanced cost management features
- **[Metrics](docs/METRICS.md)**: Performance monitoring and analytics
- **[Rate Limiting](docs/RATE_LIMIT_HANDLING.md)**: Managing API limits and cooldowns
- **[Feedback Loop](docs/FEEDBACK_LOOP.md)**: Improving prompt generation
- **[Panel Tracking](docs/PANEL_TRACKING.md)**: Advanced panel state management

---

## Project Structure

```
desktop-agent-automation/
├── automation/                 # Main package
│   ├── cli/                    # Command-line interfaces
│   ├── core/                   # Core automation logic
│   ├── desktop/                # Desktop interaction utilities
│   ├── rate_limit/             # Rate limiting and tracking
│   ├── ui/                     # UI automation components
│   ├── config.py               # Configuration management
│   ├── orchestrator.py         # Main orchestration logic
│   └── *.py                    # Various agents and utilities
├── scripts/                    # Utility scripts
├── tests/                      # Test suites
├── docs/                       # Documentation
├── schemas/                    # JSON schemas for validation
├── tasks/                      # Task files and generated prompts
├── logs/                       # Log files
├── debug/                      # Debug utilities
├── agent_assignments.json      # Task assignments
├── pyproject.toml             # Project configuration
├── requirements.txt           # Dependencies
└── README.md                  # This file
```

### Key Files
- `run_automation.py`: Main entry point for automation
- `master.py`: Unified launcher script
- `automation/config.json`: UI coordinates and settings
- `automation/state.json`: Current automation state
- `automation/metrics.json`: Performance metrics
- `agent_assignments.json`: Task management data

---

## Finished Panel Follow-Through

### Overview
The system now tracks the state of each Copilot chat panel to maximize efficiency. When a panel finishes its task (detected by 30 minutes of idle time with no output changes), the system can automatically:
1.  **Detect Completion**: Identifies when an agent has finished its work.
2.  **Verify Status**: Sends a "completion check" prompt to confirm the agent is done.
3.  **Assign New Work**: If the agent is truly finished, it assigns a new prompt from the `tasks/generated_prompts/` queue.
4.  **Round-Robin Scheduling**: Distributes new prompts evenly across available finished panels.

### Configuration
To enable this feature, set the following environment variables:
```powershell
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"
```

For safe testing, you can enable dry-run mode, which logs actions without sending them:
```powershell
$env:FINISHED_PANEL_DRY_RUN = "true"
```

### How it Works
1.  **Tracking**: `automation/panel_tracker.py` maintains a state machine for each panel (Running, Idle, Finished, etc.).
2.  **Detection**: If a panel is idle for 30 minutes, it's marked as `POSSIBLY_FINISHED`.
3.  **Verification**: The system sends a prompt: *"If you have completed your task please respond with exactly 'task completed'..."*
4.  **Action**:
    *   If the agent responds "task completed", the system fetches the next prompt from the batch file and sends it.
    *   If the agent responds with "next steps", the system encourages it to continue.

---

## Task Management CLI

The system includes a command-line tool for managing agent task assignments and tracking progress:

### Claim Tasks
```powershell
# Claim a task for an agent
python scripts/tasks_cli.py claim --id task-123 --by agent:github-copilot

# Claim with custom message
python scripts/tasks_cli.py claim --id task-123 --by human:john --message "Starting work on this"
```

### Update Task Status
```powershell
# Mark task as completed
python scripts/tasks_cli.py update-status --id task-123 --status completed --by agent:github-copilot

# Update with note and artifact
python scripts/tasks_cli.py update-status --id task-123 --status in-progress --by human:john --note "Debugging issue" --artifact logs/debug.log
```

### Add Notes to Tasks
```powershell
# Add a note with optional artifact
python scripts/tasks_cli.py add-note --id task-123 --by agent:github-copilot --message "Found root cause" --artifact screenshots/error.png
```

### View Tasks
```powershell
# List all tasks
python scripts/tasks_cli.py list

# Show task details
python scripts/tasks_cli.py show --id task-123
```

Tasks are stored in `agent_assignments.json` and validated against the schema in `schemas/agent_tasks.schema.json`.

---

## Additional Utilities & Scripts

### Log Analysis
Analyze automation logs for issues and false positives:
```powershell
# Analyze last hour of logs
python scripts/analyze_logs.py

# Analyze last 24 hours
python scripts/analyze_logs.py --hours 24
```

### Metrics Viewer
View comprehensive metrics about prompt seeding and model selections:
```powershell
python scripts/view_metrics.py
```

### Live Test Validation
Validate prerequisites before enabling finished panel follow-through:
```powershell
python scripts/validate_live_test.py
```

### Task Validation
Validate agent task assignments and check for consistency:
```powershell
# Summary of all tasks
python scripts/validate_agent_tasks.py --summary

# Detailed validation
python scripts/validate_agent_tasks.py --verbose
```

### Send to Finished Panels
Manually send confirmation prompts to panels that appear finished:
```powershell
python scripts/send_to_finished.py
```

### Desktop Scanning
Scan and interact with VS Code windows across virtual desktops:
```powershell
# Scan current desktop
python scripts/scan_desktops.py

# Click on current desktop only
python scripts/click_current_desktop.py

# Click on all desktops
python scripts/click_all_desktops.py
```

### Cost Reporting
Comprehensive cost analysis and reporting:
```powershell
# Full cost report (last 7 days)
python scripts/cost_report.py

# Cost by model
python scripts/cost_report.py --group-by model

# Show budget alerts
python scripts/cost_report.py --alerts-only
```

### Round-Robin Prompt Assignment
Prompts are now assigned in round-robin fashion across available panels:
- Each panel tracks which prompt index it received
- State persists across sessions in `automation/panel_state.json`
- Ensures even distribution of work across multiple panels

### Repository Detection
Automatic detection of repository root from VS Code window titles:
- Parses window titles like `"file.py - repo-name - Visual Studio Code"`
- Supports WSL paths: `"file.py - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code"`
- Automatically finds docs folders for master prompt generation
- Prioritizes foreground window over current working directory

---

## Testing

The project includes comprehensive test suites for all major components:

### Run All Tests
```powershell
# Run all tests
python -m pytest tests/

# With coverage
python -m pytest tests/ --cov=automation --cov-report=html
```

### Run Specific Test Suites
```powershell
# Test chat extraction functionality
python -m pytest tests/test_chat_extraction.py

# Test click verification
python -m pytest tests/test_click_verification.py

# Test master orchestrator
python -m pytest tests/test_master_prompt_orchestrator.py

# Test VS Code detection
python -m pytest tests/test_vscode_detection.py
```

### Test Coverage
Tests cover:
- UI automation and window detection
- Chat input/output handling
- Button clicking and verification
- Rate limiting and cooldown logic
- Prompt generation and assignment
- Cost tracking and metrics
- Configuration and environment handling

---

## Cost Considerations
- Each check sends a screenshot to OpenAI's vision API
- At 60-second intervals, that's ~60 API calls per hour
- Monitor your OpenAI usage dashboard and adjust `--interval` as needed
- Consider using `--once` mode triggered by hotkeys for manual control

