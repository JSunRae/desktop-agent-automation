# Metrics and Observability

This document describes the metrics collection and observability features in the desktop agent automation system.

## Overview

The system collects various metrics to track performance, success rates, and system behavior. Metrics are stored in JSON files and can be queried programmatically.

## Metrics Types

### Prompt Seeding Metrics

Tracks when prompts are sent to finished panels for follow-up work.

- **File**: `automation/metrics.json`
- **Fields**:
  - `timestamp`: When the seeding occurred
  - `panel_title`: VS Code window title
  - `prompt_index`: Index of the prompt in the batch
  - `prompt_preview`: First 100 characters of the prompt
  - `model_requested`: Model label requested (if any)
  - `success`: Whether seeding succeeded
  - `error_message`: Error details if failed

### Model Selection Metrics

Tracks model picker interactions when seeding prompts.

- **File**: `automation/metrics.json`
- **Fields**:
  - `timestamp`: When the selection occurred
  - `panel_title`: VS Code window title
  - `model_label`: Model label selected
  - `success`: Whether selection succeeded

### Assignment Tracking Metrics

Tracks which prompts are assigned to which panels for observability and debugging.

- **File**: `automation/assignment_metrics.jsonl` (JSON Lines format)
- **Fields**:
  - `timestamp`: When the assignment occurred
  - `prompt_id`: Unique hash identifier for the prompt
  - `panel_id`: Unique identifier for the panel
  - `panel_title`: VS Code window title
  - `repo`: Repository name extracted from window title (if applicable)
  - `outcome`: Assignment outcome (success/failure, determined later)

### Response Feedback Metrics

Tracks AI response analysis for learning and improvement.

- **File**: `automation/metrics.json`
- **Fields**:
  - `timestamp`: When the response was analyzed
  - `panel_title`: VS Code window title
  - `prompt_id`: Hash of the prompt that led to this response
  - `response_category`: Categorized type of response
  - `response_confidence`: Confidence score (0-1)
  - `response_sample`: Last 200 characters of response text
  - `is_sensitive`: Whether response contains sensitive data
  - `processing_time_seconds`: How long the agent worked

## Runtime Monitors

### Copilot Usage Monitor

Tracks Copilot subscription consumption pace relative to calendar progress.

- **Source**: `CopilotUsageMonitor` in `automation/copilot_usage_monitor.py`
- **Persistence**: `logs/cost_metrics.jsonl`
- **Event**: `copilot_status`
- **What it records**:
  - `percentage`: Copilot usage percent from the VS Code status bar
  - `calendar_progress`: Percent of the current month elapsed
  - `normalized_ratio`: Usage pace divided by calendar progress
  - `alert`: Warning/critical pace message when thresholds are exceeded
  - `control_name`, `automation_id`: UIA details for the matched control
- **How it runs**: Background thread started by the orchestrator during the live run loop
- **Network calls**: None. It only reads local UI Automation state and appends local JSONL metrics.

### Rate Monitor

Tracks automation throughput for Allow clicks and raises operational alerts when the click rate drops.

- **Source**: `RateMonitor` in `automation/rate_monitor.py`
- **Persistence**: No dedicated metrics file
- **What it reads**: Allow-click history from the local rate-limit tracker
- **What it emits**:
  - Local log messages for rate-drop alerts
  - Audio prompts via `speak(...)`
  - Telegram alerts via `send_telegram_alert(...)`
- **How it runs**: Inline inside the main orchestration loop

### Difference and Double-Counting

These monitors do not overlap in persisted metrics and should not be interpreted as the same signal.

- `CopilotUsageMonitor` measures subscription consumption pace from the VS Code Copilot status UI.
- `RateMonitor` measures automation throughput using local Allow-click counts.
- A high Copilot usage pace does not imply a high Allow-click rate, and a low Allow-click rate does not change Copilot usage records.

## Assignment Tracking

Assignment tracking provides observability into which prompts are sent to which panels. This helps with:

- **Debugging**: Correlate outcomes with specific prompt-panel combinations
- **Optimization**: Identify which prompts work best for different scenarios
- **Analysis**: Track assignment patterns and success rates

### Query Functions

The `MetricsTracker` class provides query functions:

```python
from automation.metrics import get_metrics_tracker

tracker = get_metrics_tracker()

# Get all assignments for a specific panel
assignments = tracker.get_assignments_by_panel(panel_id="panel123")

# Get all assignments for a specific prompt
assignments = tracker.get_assignments_by_prompt("prompt_hash")

# Get summary statistics
summary = tracker.get_summary()
```

### Thread Safety

Assignment metrics use JSON Lines format for thread-safe append operations. Multiple concurrent processes can record assignments without conflicts.

## Viewing Metrics

### Command Line

Run the metrics viewer script:

```bash
python scripts/view_metrics.py
```

### Programmatic Access

```python
from automation.metrics import get_metrics_tracker

tracker = get_metrics_tracker()
tracker.print_summary()
```

## Configuration

Metrics are automatically enabled. Files are stored in the `automation/` directory:

- `metrics.json`: Main metrics file
- `assignment_metrics.jsonl`: Assignment tracking (JSONL)

## Performance Impact

- Minimal overhead (<5% performance impact)
- Metrics are written asynchronously
- JSONL format ensures fast appends
- In-memory caching for queries

## Troubleshooting

### Missing Metrics

- Check file permissions on `automation/` directory
- Ensure `automation/metrics.py` can write to disk

### Corrupted Files

- Delete `automation/metrics.json` to reset (data will be lost)
- Delete `automation/assignment_metrics.jsonl` to reset assignments

### High Disk Usage

- Assignment metrics grow over time
- Consider periodic cleanup or archiving of old data
