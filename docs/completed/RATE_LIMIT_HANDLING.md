# Rate Limit Handling - How It Works

## Overview
The `auto_allow_copilot.py` script now automatically detects and handles Copilot rate limits by looking for "Try Again" buttons **and** the newer warning text panels that read things like "Sorry, you have been rate-limited" across all VS Code windows.

## Optimal Allow Rate (Based on Log Analysis)

Based on analysis of `allow_metrics.jsonl` logs:

| Allows/Hour | Allows/Minute | Risk Level | Notes |
|-------------|---------------|------------|-------|
| 50-60 | ~1.0 | ✅ Safe | Sustainable for overnight/unattended use |
| 70-90 | 1.2-1.5 | ⚠️ Moderate | May trigger occasional rate limits |
| 100+ | >1.7 | ❌ High | Frequently triggers rate limits |

**Recommendations:**
- For 10 agents: Each can do ~5-6 tool calls/hour sustainably
- Cooldown of 20 minutes is optimal for recovery
- TF and Trading desktops are prioritized for Allow clicks

## Window Priority System (NEW!)

Windows are now processed in priority order to maximize valuable work:

1. **TF desktop/project windows** - Highest priority (processed first)
2. **Trading desktop/project windows** - Second priority  
3. **All other windows** - Processed after priority windows

This ensures high-value agents get Allow clicks before rate limits trigger.

### Configuration
```python
WINDOW_PRIORITY_PATTERNS = [
    "tf",           # TF desktop/project windows - highest priority
    "trading",      # Trading desktop/project windows - second priority
]
```

## Smart Rate Limit Verification (NEW!)

A key improvement is **verification before cooldown**. The script no longer blindly trusts rate limit indicators - it verifies them by:

1. **Clicking additional Allow buttons** after detecting a suspected rate limit
2. **Monitoring for activity** (new output appearing in the chat panel)
3. **Distinguishing between "agent is working" vs "true rate limit"**

### Why Verification?
Sometimes agents appear rate-limited but are actually still working:
- Rate limit messages can persist from previous interactions
- UI can briefly show rate limit indicators before updating
- Stale panels may trigger false positives

### How Verification Works
When rate limit indicators are detected:
1. The script finds available Allow buttons
2. Clicks up to 2 additional Allow buttons (configurable via `RATE_LIMIT_VERIFY_CLICKS`)
3. Waits 3 seconds per click watching for new output (configurable via `RATE_LIMIT_VERIFY_WAIT_SECONDS`)
4. If new text appears → Agent is working, NOT rate limited → Continue normal operation
5. If rate limit message appears immediately → Confirmed rate limit → Enter cooldown

### Configuration
```python
RATE_LIMIT_VERIFY_CLICKS = 2        # Number of extra Allow clicks to verify
RATE_LIMIT_VERIFY_WAIT_SECONDS = 3.0  # Time to wait for activity after each click
RATE_LIMIT_ACTIVITY_CHECK_INTERVAL = 0.5  # How often to check for activity
```

## How It Works

### Phase 1: Rate Limit Detection
1. **Scans all VS Code windows** for "Try Again" buttons AND Copilot's textual rate-limit panels
2. **Verification step**: If indicators found, clicks Allow buttons to confirm
3. **Global detection**: If verified, rate limit applies to ALL windows
4. **Conditional cooldown**: Only enters cooldown if rate limit is confirmed

### Phase 2: Cooldown Period
- **Duration**: 20 minutes (configurable via `COOLDOWN_MINUTES`)
- **Live countdown**: Shows remaining time in MM:SS format
- **No checking**: Script pauses ALL button clicking during this period
- **Updates every 5 seconds**: Keeps you informed of progress

### Phase 3: Recovery
1. **Clicks all "Try Again" buttons** across all windows simultaneously
2. **Grace period**: 5 minutes where pre-existing rate limit indicators are ignored
3. **Resumes normal operation**: Returns to checking for Allow/Keep Edits buttons
4. **Clean restart**: Full automation continues as before

## Focus Terminal Button Handling

The script detects "Focus Terminal" buttons that require user attention. To prevent alert fatigue from repeated notifications for the same window:

### Deduplication
- Alerts for the same window are suppressed for a configurable time period (default: 30 minutes)
- Only the first occurrence triggers audio/visual alerts
- Text-to-speech can be disabled via `FOCUS_TERMINAL_SPEAK_ALERTS`

### Configuration
```python
FOCUS_TERMINAL_DEDUPE_MINUTES = 30  # Suppress repeated alerts for same window
FOCUS_TERMINAL_SPEAK_ALERTS = true  # Enable/disable TTS for Focus Terminal alerts
```

## Desktop Switching Reliability

When using multiple virtual desktops, the script now tracks desktop reliability:

### Smart Desktop Skipping
- Desktops that consistently fail to show windows are temporarily skipped
- After N consecutive failures, the desktop is skipped for M cycles
- Periodically re-checks "failed" desktops to detect restored windows

### Configuration
```python
DESKTOP_MAX_CONSECUTIVE_FAILURES = 3  # Skip after this many consecutive failures
DESKTOP_RECHECK_AFTER_FAILURES = 5    # Re-check failed desktop after this many cycles
```

## Log Verbosity Control

Reduce console spam by adjusting the log verbosity level:

### Verbosity Levels
- **`normal`** (default): Standard output - shows important events and status updates
- **`quiet`**: Minimal output - only shows critical events (rate limits, clicks, errors)
- **`verbose`**: Full detail - includes all scan steps, retries, and per-window checks

### Configuration
```python
LOG_VERBOSITY = "normal"  # Options: "normal", "quiet", "verbose"
```

Or set via environment variable:
```bash
set LOG_VERBOSITY=quiet
python auto_allow_copilot.py
```

### What Each Level Shows
| Event Type | quiet | normal | verbose |
|------------|-------|--------|---------|
| Rate limit detection | ✓ | ✓ | ✓ |
| Button clicks | ✓ | ✓ | ✓ |
| Errors | ✓ | ✓ | ✓ |
| Desktop switching | | ✓ | ✓ |
| Window counts | | ✓ | ✓ |
| Per-window scanning | | | ✓ |
| Retry attempts | | | ✓ |
| Grace period details | | | ✓ |

## Key Features

### Global Rate Limit Recognition
- **One limit for all**: Rate limits apply globally, not per-window
- **Efficient scanning**: Checks all windows quickly to find any rate limit state
- **Immediate response**: Stops clicking buttons as soon as rate limit detected

### Smart Panel Detection
The script now detects four types of Copilot UI elements:
1. **"Allow (Ctrl+Enter)"** - Command confirmation buttons
2. **"Keep All Edits (Ctrl+Enter)"** - Edit acceptance buttons
3. **"Try Again"** - Rate limit recovery buttons
4. **Rate-limit panels** - Warning groups that say things like "Sorry, you have been rate-limited" (NEW!)

### Stale Panel Suppression
Some VS Code chat panes retain historic "Sorry, you have been rate-limited" text even after recovery. The automation now:

- **Ignores long transcripts** where the match appears deep inside the text (configurable via `RATE_LIMIT_STALE_TEXT_LENGTH` and `RATE_LIMIT_PATTERN_MAX_OFFSET`).
- **Dedupes previously-seen panels** for several hours (`RATE_LIMIT_PANEL_DEDUPE_MINUTES`) so the same stale control can't repeatedly trigger new cooldown cycles.
- Still responds instantly to fresh panels or visible "Try Again" buttons, so real rate-limit events continue to pause automation.

Tune these settings through environment variables if your workspace behaves differently:

```python
RATE_LIMIT_STALE_TEXT_LENGTH = 800       # characters; set 0 to disable length heuristic
RATE_LIMIT_PATTERN_MAX_OFFSET = 360      # characters; max index within text before it's considered stale
RATE_LIMIT_PANEL_DEDUPE_MINUTES = 180    # minutes to remember previously seen panels
```

### Non-Intrusive Operation
- **Saves mouse position**: Returns cursor to original location
- **Preserves focus**: Keeps your active window focused
- **Background operation**: Doesn't interrupt your work

## Configuration

```python
COOLDOWN_MINUTES = 10  # Duration to wait when rate limit detected
CHECK_INTERVAL_SECONDS = 3  # How often to check for buttons
```

## Example Output

```
[2025-11-23 14:50:54] Scanning for rate limit 'Try Again' buttons...
  Found 1 'Try Again' button(s) in 'OBJECTIVE: - tf_1 [WSL: Ubuntu-24.04]...'
  Found 1 'Try Again' button(s) in 'Trading Data Spec Audit...'
  Found rate limit message in 'CLIPBOARD.md - tf_1 [WSL: Ubuntu-24.04]...'
    ↳ " Sorry, you have been rate-limited. Please wait a moment before trying again. …"

======================================================================
[2025-11-23 14:50:54] RATE LIMIT DETECTED!
  Found 4 'Try Again' button(s) across all windows
  Detected 1 rate limit message panel(s) even without buttons
  Entering 10-minute cooldown...
  Will click all 'Try Again^
  ' buttons after cooldown expires
======================================================================
^

[2025-11-23 14:50:59] Cooldown: 19:55 remaining  
[2025-11-23 14:51:04] Cooldown: 19:50 remaining  
...
[2025-11-23 15:10:54] Cooldown: 00:00 remaining  

[2025-11-23 15:10:54] Cooldown complete! Clicking 'Try Again' buttons...
  ✓ Clicked 'Try Again' button 1/4
  ✓ Clicked 'Try Again' button 2/4
  ✓ Clicked 'Try Again' button 3/4
  ✓ Clicked 'Try Again' button 4/4
[2025-11-23 15:10:56] Rate limit recovery complete. Resuming normal operation.
```

## Testing

Use the standalone test script to verify detection:

```powershell
python test_try_again_button.py
```

This will:
1. Find all "Try Again" buttons
2. Show you which windows have them
3. Wait 20 minutes
4. Click them all automatically

## Technical Details

### Button Detection
- **Recursive search**: Deep scan through UI hierarchy (up to 50 levels)
- **Pattern matching**: Looks for buttons with "Try Again" in the name
- **Existence check**: Verifies each button is accessible before clicking

### UI Automation
- **Chrome render widgets**: Works even though buttons are in Chrome_RenderWidgetHostHWND
- **Instant clicking**: Uses Win32 API for fast, reliable clicks
- **Error handling**: Gracefully handles buttons that disappear

### Desktop Support
- Works with the `DESKTOPS_TO_CHECK` configuration
- Scans all configured desktops for rate limit buttons
- Clicks buttons across all desktops after cooldown
