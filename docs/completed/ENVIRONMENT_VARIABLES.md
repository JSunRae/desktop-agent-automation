# Environment Variable Setup Guide

This guide explains all environment variables used by the desktop agent automation system.

## Finished Panel Follow-Through

### ENABLE_FINISHED_PANEL_FOLLOWUPS

- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Purpose**: Master toggle for finished panel automation
- **Usage**: Set to `true` to enable automatic follow-through on finished panels

```powershell
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
```

### FINISHED_PANEL_DRY_RUN

- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Purpose**: Dry-run mode - logs actions without executing UI changes
- **Usage**: Set to `true` for safe testing

```powershell
$env:FINISHED_PANEL_DRY_RUN = "true"
```

### ENABLE_SEND_TO_INACTIVE_PANELS

- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Purpose**: Safety gate - allows sending text to inactive panels
- **Usage**: Must be `true` for finished panel automation to work

```powershell
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"
```

### FINISHED_PANEL_PROMPT_PATH

- **Type**: File path
- **Default**: `tasks/generated_prompts/latest.txt`
- **Purpose**: Path to prompt batch file
- **Usage**: Override to use a different prompt file. This path is also used as the _root_ for auto-discovered per-repo prompt feeds.

```powershell
$env:FINISHED_PANEL_PROMPT_PATH = "path\to\prompts.txt"
```

### REPO_PROMPT_MAP

- **Type**: Mapping (JSON object or semicolon-delimited `name=path`)
- **Default**: empty
- **Purpose**: Route specific repositories (derived from VS Code window titles) to specific prompt-feed files.
- **Usage**: Use this when you want a repo to read from a custom prompt file that is not in the auto-generated layout.

JSON example:

```powershell
$env:REPO_PROMPT_MAP = '{"ProjectA": "tasks/generated_prompts/ProjectA/latest.txt"}'
```

Semicolon-delimited example:

```powershell
$env:REPO_PROMPT_MAP = 'ProjectA=tasks/generated_prompts/ProjectA/latest.txt;ProjectB=tasks/project_b_prompts.txt'
```

## Repo-Specific Prompt Feeds (How Routing Works)

Prompt feed routing is centralized in `automation/prompt_resolver.py` and used by both the finished-panel tracker and task dispatcher.

Resolution order for a repo:

1. **Explicit mapping**: If the repo name matches a key in `REPO_PROMPT_MAP` (case-insensitive), use that mapped file path.
2. **Auto-generated layout**: Otherwise, look for `<FINISHED_PANEL_PROMPT_PATH parent>/<RepoName>/latest.txt` and use it _if it exists_.
3. **Fallback**: Otherwise, use `FINISHED_PANEL_PROMPT_PATH`.

## Master Agent Configuration

### NO_ALLOW_TRIGGER_MINUTES

- **Type**: Integer (minutes)
- **Default**: `60`
- **Purpose**: Trigger master agent after this many minutes without Allow clicks
- **Usage**: Adjust based on workflow needs

### PROMPT_GENERATION_COOLDOWN_MINUTES

- **Type**: Integer (minutes)
- **Default**: `90`
- **Purpose**: Minimum time between master agent runs
- **Usage**: Prevents excessive API calls

### OPENAI_COORDINATION_MODEL

- **Type**: String (model name)
- **Default**: `gpt-5.4`
- **Purpose**: Shared default model for text-only OpenAI coordination workflows
- **Usage**: Acts as the fallback default for master prompt generation, handover summaries, panel classification, and finished-panel review unless a workflow-specific override is set

### HANDOVER_SUMMARY_MODEL

- **Type**: String (model name)
- **Default**: Inherits `OPENAI_COORDINATION_MODEL`
- **Purpose**: OpenAI model for handover transcript summarization

### PANEL_CLASSIFICATION_MODEL

- **Type**: String (model name)
- **Default**: Inherits `OPENAI_COORDINATION_MODEL`
- **Purpose**: OpenAI model for classifying panel output before reseeding

### MASTER_AGENT_MODEL

- **Type**: String (model name)
- **Default**: `gpt-5.4`
- **Purpose**: OpenAI model for master orchestrator
- **Options**: `gpt-5.4`, `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, etc.

### FINISHED_PANEL_REVIEW_MODEL

- **Type**: String (model name)
- **Default**: Inherits `OPENAI_COORDINATION_MODEL`
- **Purpose**: OpenAI model for finished-panel completion review

### AUTO_ALLOW_COMPUTER_USE_MODEL

- **Type**: String (model name)
- **Default**: `computer-use-preview`
- **Purpose**: OpenAI computer-use model for the desktop auto-allow agent's primary click-detection path

### AUTO_ALLOW_VISION_FALLBACK_MODEL

- **Type**: String (model name)
- **Default**: `gpt-4o`
- **Purpose**: Vision-capable chat model used by the desktop auto-allow agent when the computer-use model is unavailable

### MASTER_AGENT_MAX_DOCS

- **Type**: Integer
- **Default**: `18`
- **Purpose**: Maximum number of documents to include in context

### MASTER_AGENT_MAX_CHARS

- **Type**: Integer
- **Default**: `3500`
- **Purpose**: Maximum characters per document

## Path Configuration

### MASTER_AGENT_DOCS_ROOT

- **Type**: Directory path
- **Default**: `\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\tf_1\docs`
- **Purpose**: Root directory for docs to scan
- **Usage**: Override for different workspace

### MASTER_AGENT_OPEN_TASKS_ROOT

- **Type**: Directory path
- **Default**: `{MASTER_AGENT_DOCS_ROOT}/open_tasks`
- **Purpose**: Directory containing open task files

### MASTER_AGENT_PROMPT_DIR

- **Type**: Directory path
- **Default**: `tasks/generated_prompts`
- **Purpose**: Where master agent saves generated prompts

### MASTER_AGENT_REPO_CONFIGS

- **Type**: JSON array or semicolon-delimited string
- **Default**: None (uses auto-detection)
- **Purpose**: Configure multiple repositories for prompt generation
- **Usage**: Define repo-specific document paths for multi-repo support

```json
[
  {
    "name": "repo1",
    "docs_dirs": ["/path/to/repo1/docs", "/path/to/repo1/tasks"]
  },
  { "name": "repo2", "docs_dirs": ["/path/to/repo2/docs"] }
]
```

Or semicolon-delimited:

```
repo1=/path/to/repo1/docs,/path/to/repo1/tasks;repo2=/path/to/repo2/docs
```

## Rate Limiting

### MAX_ALLOWS_PER_HOUR

- **Type**: Integer
- **Default**: `70`
- **Purpose**: Maximum Allow button clicks per 60-minute rolling window
- **Safe range**: 50-60
- **Risky**: 100+

### RATE_LIMIT_BUFFER_SECONDS

- **Type**: Integer (seconds)
- **Default**: `5`
- **Purpose**: Safety margin after oldest event expires

## Logging & Alerts

### LOG_VERBOSITY

- **Type**: String
- **Default**: `normal`
- **Options**: `quiet`, `normal`, `verbose`
- **Purpose**: Controls console output detail level

### ENABLE_NO_CLICK_ALERT

- **Type**: Boolean (`true`/`false`)
- **Default**: `true`
- **Purpose**: Enable audio alert when no clicks occur for extended period

### NO_CLICK_ALERT_MINUTES

- **Type**: Integer (minutes)
- **Default**: `15`
- **Purpose**: Minutes without clicks before alert triggers

## Timing Configuration

### COOLDOWN_MINUTES

- **Type**: Integer (minutes)
- **Default**: `10`
- **Purpose**: Cooldown duration after rate limit detection

### POST_COOLDOWN_GRACE_MINUTES

- **Type**: Integer (minutes)
- **Default**: `5`
- **Purpose**: Grace period after cooldown to ignore pre-existing rate limit indicators

### MIN_SCAN_INTERVAL_SECONDS

- **Type**: Float (seconds)
- **Default**: `0.5`
- **Purpose**: Minimum time between scans (prevents CPU thrashing)

## Complete Setup Example

### For Development/Testing (Dry-Run)

```powershell
# Enable finished panel automation in dry-run mode
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:FINISHED_PANEL_DRY_RUN = "true"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# Verbose logging for debugging
$env:LOG_VERBOSITY = "verbose"

# Run the orchestrator
python -m automation.orchestrator
```

### For Production (Live Mode)

```powershell
# Enable finished panel automation in live mode
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:FINISHED_PANEL_DRY_RUN = "false"  # or omit - false is default
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# Conservative rate limiting
$env:MAX_ALLOWS_PER_HOUR = "50"

# Normal logging
$env:LOG_VERBOSITY = "normal"

# Run the orchestrator
python -m automation.orchestrator
```

### Disable Finished Panel Automation

```powershell
# Simply set the master toggle to false
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "false"

# Or unset it entirely
Remove-Item Env:\ENABLE_FINISHED_PANEL_FOLLOWUPS
```

## Environment Variable Persistence

To make environment variables persist across sessions, add them to your PowerShell profile:

```powershell
# Edit your PowerShell profile
notepad $PROFILE

# Add variables (example):
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"
```

Or create a `.env` file in the project root (automatically loaded by `python-dotenv`):

## Rate Limit Detection Tuning

### RATE_LIMIT_STALE_TEXT_LENGTH

- **Type**: Integer
- **Default**: `800`
- **Purpose**: Minimum text length to consider for stale detection

### RATE_LIMIT_PATTERN_MAX_OFFSET

- **Type**: Integer
- **Default**: `360`
- **Purpose**: How far back to search for rate limit patterns

### RATE_LIMIT_PANEL_DEDUPE_MINUTES

- **Type**: Integer
- **Default**: `180`
- **Purpose**: Time to remember a rate-limited panel

### RATE_LIMIT_RECENT_TEXT_WINDOW

- **Type**: Integer
- **Default**: `400`
- **Purpose**: Size of text window for recent activity check

### RATE_LIMIT_SEGMENT_PREVIEW_CHARS

- **Type**: Integer
- **Default**: `140`
- **Purpose**: Number of characters to preview in segments

### RATE_LIMIT_SEGMENT_MAX_COUNT

- **Type**: Integer
- **Default**: `3`
- **Purpose**: Maximum number of segments to check

### RATE_LIMIT_VERIFY_CLICKS

- **Type**: Integer
- **Default**: `1`
- **Purpose**: Number of extra Allow clicks to verify rate limit

### RATE_LIMIT_VERIFY_WAIT_SECONDS

- **Type**: Float
- **Default**: `1.5`
- **Purpose**: Time to wait for activity after each click

### RATE_LIMIT_ACTIVITY_CHECK_INTERVAL

- **Type**: Float
- **Default**: `0.3`
- **Purpose**: How often to check for activity during verification

### TRY_AGAIN_COOLDOWN_MINUTES

- **Type**: Integer
- **Default**: `5`
- **Purpose**: Cooldown when rate limit is detected via Try Again button

## Feature Toggles & Alerts

### ENABLE_CLIPBOARD_TEXT_READING

- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Purpose**: Use clipboard to read chat input (can be unreliable)

### ENABLE_NO_CLICK_ALERT

- **Type**: Boolean (`true`/`false`)
- **Default**: `true`
- **Purpose**: Speak a warning if no clicks occur for a while

### NO_CLICK_ALERT_MINUTES

- **Type**: Integer
- **Default**: `15`
- **Purpose**: Minutes without clicks before alerting

### FOCUS_TERMINAL_DEDUPE_MINUTES

- **Type**: Integer
- **Default**: `30`
- **Purpose**: Deduplication window for focus terminal alerts

### FOCUS_TERMINAL_SPEAK_ALERTS

- **Type**: Boolean (`true`/`false`)
- **Default**: `true`
- **Purpose**: Speak alerts when terminal focus is lost

### LOG_VERBOSITY

- **Type**: String (`normal`/`quiet`/`verbose`)
- **Default**: `normal`
- **Purpose**: Logging detail level

## Metrics & Logging Paths

### ALLOW_METRICS_LOG_PATH

- **Type**: File path
- **Default**: `automation/allow_metrics.jsonl`
- **Purpose**: Path to metrics log file

### ALLOW_EVENTS_PERSIST_PATH

- **Type**: File path
- **Default**: `automation/allow_events.json`
- **Purpose**: Path to persisted events file

### ALLOW_METRICS_INTERVAL_SECONDS

- **Type**: Integer
- **Default**: `300`
- **Purpose**: Interval for metrics logging

### ALLOW_EVENT_RETENTION_MINUTES

- **Type**: Integer
- **Default**: `60`
- **Purpose**: How long to keep allow events in memory

## Model Picker UI Dependencies

### Overview

The model picker UI allows users to select which AI model (Grok, Codex variants) to use for generated prompts in VS Code Copilot Chat. This feature automatically detects model preferences from prompt headers and selects the appropriate model in the Copilot interface.

### UI Components Required

#### VS Code Extensions

- **GitHub Copilot** (required) - Core Copilot functionality
- **GitHub Copilot Chat** (required) - Chat interface with model picker

#### Copilot Chat Interface Elements

- **Model Picker Button**: Named "Pick Model (Ctrl+Alt+.)"
- **Model Selection Menu**: Dropdown with available models
- **New Chat Button**: For opening fresh chat sessions

### System Dependencies

#### Operating System

- **Windows** (required) - Uses Windows UI Automation API
- **Python Version**: 3.11+ (from pyproject.toml)

#### VS Code Requirements

- **VS Code Version**: 1.80+ (recommended for stable Copilot integration)
- **Copilot Access**: Active GitHub Copilot subscription
- **Copilot Chat**: Enabled and accessible

### Supported Models

The system supports these models via the picker:

| Model Key    | UI Label                      | Notes                       |
| ------------ | ----------------------------- | --------------------------- |
| `grok`       | "Grok"                        | xAI's Grok model            |
| `codex-mini` | "GPT-5.1 Codex Mini"          | Lightweight Codex variant   |
| `codex`      | "GPT-5.1 Codex"               | Standard Codex model        |
| `codex-max`  | "GPT-5.1-Codex-Max (Preview)" | High-capacity preview model |

### Setup Instructions

#### 1. Install Required VS Code Extensions

```bash
# In VS Code Command Palette (Ctrl+Shift+P):
# "Extensions: Install Extension" > Search for:
- "GitHub Copilot"
- "GitHub Copilot Chat"
```

#### 2. Enable Copilot Chat

1. Open VS Code
2. Press `Ctrl+Alt+I` to open Copilot Chat
3. Verify the chat panel opens with model picker visible

#### 3. Configure Environment Variables

```powershell
# Enable finished panel follow-through (required for model picker)
$env:ENABLE_FINISHED_PANEL_FOLLOWUPS = "true"
$env:ENABLE_SEND_TO_INACTIVE_PANELS = "true"

# Optional: Dry-run mode for testing
$env:FINISHED_PANEL_DRY_RUN = "true"
```

#### 4. Test Model Picker Access

```powershell
# Run the orchestrator to test
python -m automation.orchestrator
```

### Integration with Prompt Generation

#### Automatic Model Detection

The system automatically detects model preferences from prompt headers:

```markdown
1. Codex Mini Prompt
   This prompt will use GPT-5.1 Codex Mini

2. Grok Analysis Task  
   This prompt will use Grok
```

#### Fallback Behavior

- If no model specified in prompt: Uses Copilot's default model
- If specified model unavailable: Falls back to default
- If model picker fails: Continues with default model

### Common Issues and Troubleshooting

#### "Model picker not found" Error

**Symptoms**: Logs show "Model picker button not found"
**Solutions**:

1. Verify Copilot Chat is open (`Ctrl+Alt+I`)
2. Check button name: Should be "Pick Model (Ctrl+Alt+.)"
3. Ensure VS Code is focused and Copilot has loaded
4. Try restarting VS Code

#### "Model not available" Error

**Symptoms**: Specified model not in dropdown
**Solutions**:

1. Check Copilot subscription includes requested model
2. Verify model name matches exactly (case-sensitive)
3. Some models may be in preview/beta status

#### UI Not Responding

**Symptoms**: Model selection clicks don't work
**Solutions**:

1. Ensure VS Code window is active (not minimized)
2. Wait for Copilot Chat to fully load (spinner disappears)
3. Check for VS Code updates
4. Restart Copilot Chat extension

#### Permission Issues

**Symptoms**: Cannot access Copilot Chat
**Solutions**:

1. Verify GitHub Copilot subscription is active
2. Check VS Code signed into GitHub account
3. Ensure Copilot extensions are enabled

### Testing on Fresh VS Code Installation

#### Prerequisites

- Clean VS Code installation (no existing extensions)
- GitHub account with Copilot access
- Windows 10/11

#### Step-by-Step Test

1. **Install VS Code** (latest version)
2. **Sign into GitHub** in VS Code
3. **Install Copilot extensions**:
   - GitHub Copilot
   - GitHub Copilot Chat
4. **Restart VS Code**
5. **Open Copilot Chat** (`Ctrl+Alt+I`)
6. **Verify model picker** appears in chat toolbar
7. **Test model selection** by clicking picker and selecting a model
8. **Run automation** with dry-run mode first

#### Expected Results

- Copilot Chat opens successfully
- Model picker button visible and clickable
- All supported models appear in dropdown
- Model selection changes chat behavior
- Automation can detect and select models

### Cross-References

- **Quick Start**: See `QUICKSTART_FINISHED_PANELS.md` for live testing
- **Architecture**: See `ARCHITECTURE.md` for system overview
- **Panel Tracking**: See `PANEL_TRACKING.md` for integration details
- **Configuration**: See `automation/config.py` for model label definitions

```bash
# .env file
ENABLE_FINISHED_PANEL_FOLLOWUPS=true
ENABLE_SEND_TO_INACTIVE_PANELS=true
FINISHED_PANEL_DRY_RUN=false
LOG_VERBOSITY=normal
MAX_ALLOWS_PER_HOUR=60
```

---

_Last updated: December 8, 2025_
