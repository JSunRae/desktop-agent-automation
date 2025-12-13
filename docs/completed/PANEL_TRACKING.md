# Panel Tracking System

This document describes the panel tracking system that monitors Copilot chat panels for activity and sends follow-up prompts to finished panels.

## Overview

The panel tracking system:
1. **Logs panels** we've clicked Allow or Keep on
2. **Monitors activity** - tracks if output is still changing
3. **Detects running state** - checks for Cancel vs Send button
4. **Identifies idle reasons** - waiting for Allow, rate limited, or possibly finished
5. **Handles rate limits** - sends "please continue" when needed
6. **Sends follow-up prompts** - asks if task is complete or has next steps

## Panel States

| State | Icon | Description |
|-------|------|-------------|
| **RUNNING** | ■ | Cancel button visible - agent actively working |
| **WAITING_ALLOW** | ⏸ | Allow button visible - needs user click |
| **RATE_LIMITED** | ⚠ | Rate limit detected - has Try Again button OR needs "please continue" |
| **IDLE** | ▶ | No special buttons - might be finished or awaiting user |
| **FINISHED** | ✓ | Output unchanged for 30+ min, idle |
| **COMPLETED** | ✓✓ | Agent responded with "task completed" |

## Idle Reasons

When a panel is not running (has Send button instead of Cancel), the system determines why:

| Reason | Description | Auto-Action |
|--------|-------------|-------------|
| `WAITING_ALLOW` | Allow button needs to be clicked | Main loop handles |
| `RATE_LIMITED_BUTTON` | Try Again button visible | Click Try Again |
| `RATE_LIMITED_NO_BUTTON` | Rate limit text but no button | Send "please continue" |
| `POSSIBLY_FINISHED` | No buttons, might be done | Send completion check |
| `AWAITING_USER` | Waiting for user input | None |

## How It Works

### 1. Recording Allow Clicks
When an Allow or Keep button is clicked, the panel is recorded:
- Window title is logged
- Timestamp is stored
- Panel marked as RUNNING

### 2. Detecting Running vs Idle
Each scan cycle checks the toolbar:
- **Cancel (Alt+Backspace)** visible → Agent is RUNNING (working)
- **Send button** visible → Agent is IDLE (determine reason)

### 3. Idle Reason Detection
When idle, the system checks for:
1. Allow button → `WAITING_ALLOW`
2. Try Again button → `RATE_LIMITED_BUTTON`
3. Rate limit text in output (no button) → `RATE_LIMITED_NO_BUTTON`
4. None of the above → `POSSIBLY_FINISHED`

### 4. Rate Limit Handling

Two types of rate limiting are handled:

**With Try Again Button:**
- System detects and logs it
- Main loop clicks Try Again when found

**Without Try Again Button:**
- Output contains rate limit text
- System automatically sends: `"please continue"`
- Resets after panel starts running again

### 5. Output Monitoring
The last 100 characters of output are sampled:
- If text changes → Panel still active
- If no change for 30 min → Panel is FINISHED

### 6. Follow-up Prompts

For finished panels, the system:

1. **Classifies panel output** using OpenAI GPT-4o-mini to determine safety:
   - `IDLE_SAFE`: Safe to seed new prompts
   - `ACTIVE_WORKING`: Agent still working - skip seeding
   - `COMPLETED`: Task completed - skip seeding  
   - `AWAITING_USER`: Waiting for user input - skip seeding

2. **Only seeds prompts if classified as `IDLE_SAFE`**

3. **Sends appropriate follow-up prompts** based on output content:

**If output contains "next steps":**
```
Review your thought process and recommendations. 
You may continue working on the next steps as you best recommend.
```

**If no "next steps" mentioned:**
```
If you have completed your task please respond with exactly 'task completed', 
if you have follow up actions you recommend, respond with 'next steps' and your proposal.
```

### 7. Priority System

Panels are prioritized for Allow button checking:
- **RUNNING panels** → Highest priority (checked first)
- **WAITING_ALLOW panels** → High priority
- **RATE_LIMITED panels** → Medium priority
- **IDLE/FINISHED panels** → Lowest priority
- **COMPLETED panels** → Only checked when idle capacity remains

## Configuration

In `automation/panel_tracker.py`:

```python
# Timing thresholds
PANEL_IDLE_THRESHOLD_MINUTES = 30      # Mark idle after this long without clicks
PANEL_FINISHED_THRESHOLD_MINUTES = 30  # Mark finished if output unchanged
OUTPUT_SAMPLE_CHARS = 100              # Characters to sample for change detection

# Classification settings
CLASSIFICATION_TEXT_LIMIT = 1000       # Max characters sent to OpenAI for classification

# Rate limit handling
PLEASE_CONTINUE_PROMPT = "please continue"  # Sent when rate limited without button
```

### Panel Output Classification

Before seeding new prompts, the system uses OpenAI's GPT-4o-mini to classify the panel's output:

- **Model:** `gpt-4o-mini` (cost-effective)
- **Input:** Last 1000 characters of panel output
- **Cost:** ~$0.002 per classification (very low)
- **Fallback:** Defaults to `IDLE_SAFE` on API errors
- **Purpose:** Prevent inappropriate seeding on active/completed panels

**Classification Categories:**
- `IDLE_SAFE`: Safe to seed new prompts
- `ACTIVE_WORKING`: Agent currently working - skip
- `COMPLETED`: Task finished - skip  
- `AWAITING_USER`: Waiting for user input - skip

## State Persistence

Panel state is persisted to `automation/panel_state.json` and survives restarts.

## UI Detection

### Detecting Running State (Cancel vs Send Button)

| Button | Icon | State | Meaning |
|--------|------|-------|---------|
| `Cancel (Alt+Backspace)` | ■ Square | RUNNING | Agent is actively working |
| `Send [Alt] Send to New Chat (Ctrl+Shift+Enter)` | ▶ Arrow | IDLE | Ready for input |

**Detection logic:**
1. Search for "Cancel" button with "Alt+Backspace" in name → **RUNNING**
2. Search for "Send" button (no "Cancel" in name) → **IDLE**
3. Neither found → Window has no chat panel

### Finding the Chat Input
To send follow-up prompts, the system locates the chat input by:
1. Looking for Chrome_RenderWidgetHostHWND controls
2. Finding the toolbar area with Send button
3. Using clipboard paste + Enter for reliable text entry

## Logging

Panel tracker events are logged with the `[PanelTracker]` prefix:
```
[PanelTracker] Panel now IDLE (no Allow clicks for 30min): MyProject - Visual Studio...
[PanelTracker] Panel now FINISHED (output unchanged for 30min): MyProject - Visual Studio...
[PanelTracker] Rate limited (no button) - sending 'please continue': MyProject...
[PanelTracker] Sent text to chat: If you have completed your task...
[PanelTracker] Panel marked COMPLETED: MyProject - Visual Studio...
```

## Status Summary

A status summary is printed every 10 minutes:
```
============================================================
[PanelTracker] Panel Status Summary
============================================================

RUNNING (2):
  • [■ WORKING] ProjectA - Visual Studio Code... (last: 5min ago)
  • [■ WORKING] ProjectB - Visual Studio Code... (last: 12min ago)

RATE_LIMITED (1):
  • [⚠ RATE LIMITED - Need 'continue'] ProjectC - Visual... (last: 8min ago)

FINISHED (1):
  • [▶ POSSIBLY DONE] OldProject - Visual Studio Code... (last: 45min ago)

COMPLETED (1):
  • [✓ COMPLETE] DoneProject - Visual Studio Code... (last: 120min ago)
============================================================
```

## Integration

The panel tracker integrates with the main `auto_allow_copilot.py`:
1. Each Allow click calls `on_allow_click()`
2. Each window scan calls `update_panel_from_window()`
3. After main scans, `process_finished_panels()` sends completion prompts
4. `process_rate_limited_panels()` sends "please continue" for stuck panels
5. Window priority uses `get_window_priority()` for sorting

## Functions

### Core Functions
- `on_allow_click(window_title, panel_id)` - Record when Allow/Keep clicked
- `update_panel_from_window(vs_win)` - Update panel state from UI inspection
- `get_comprehensive_panel_state(vs_win)` - Get full state with idle reason

### Processing Functions
- `process_finished_panels(windows)` - Send follow-up prompts to finished panels
- `process_rate_limited_panels(windows)` - Send "please continue" when rate limited

### Detection Functions
- `detect_panel_running_state(vs_win)` - Check Cancel vs Send button
- `detect_idle_reason(vs_win)` - Determine why panel is idle
- `check_for_task_completed(vs_win)` - Check if output says "task completed"

### Utility Functions
- `get_window_priority(window_title)` - Get priority for window ordering
- `print_tracker_status()` - Print status summary
- `should_check_finished_panels(remaining_clicks, live_found)` - Decision helper
