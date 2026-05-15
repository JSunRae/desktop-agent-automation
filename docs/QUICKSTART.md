# Desktop Auto-Allow Agent - Quick Start Guide

## Orchestration V1 Operator Quickstart

If you are operating orchestration v1, use this sequence before the older desktop auto-allow workflow below.

Safe order:

0. Run `master --run launch-preflight` on the operator machine and clear any failing launch blockers before live use.
1. Run preflight.
2. Run readiness-only for the exact window id.
3. Rehearse with live dry-run if you are testing a new targeting path.
4. Run live pilot only after readiness reports `ready_to_send`.

Minimal commands:

```powershell
# 1. Read-only preflight
python scripts\orchestration_v1.py --pilot-preflight --pilot-preflight-repo trading --json

# 2. Readiness-only probe for one exact repo window
python scripts\orchestration_v1.py --pilot-readiness-only --pilot-readiness-repo trading --pilot-window-id <window_id> --json

# 3. Optional repo-targeted live dry-run rehearsal
python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-dry-run --pilot-dry-run-repo trading --pilot-window-id <window_id> --json

# 4. Live pilot with fail-closed activation checks
python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-safe-activate --pilot-window-id <window_id> --json
```

Primary references:

- `docs/ORCHESTRATION_V1_OPERATOR_RUNBOOK.md`
- `docs/QUICK_REFERENCE.md`
- `docs/ORCHESTRATION_V1_STRICT_RESPONSE_GUIDE.md`
- `docs/pilot_window_targeting_checklist.md`

Use the rest of this file for the legacy desktop auto-allow setup and monitor-capture workflow.

## ✅ Installation Complete!

## Developer setup (tests + lint)

```powershell
pip install -e ".[dev]"
```

or, to use the curated requirements/constraints pair:

```powershell
pip install -r requirements-dev.txt -c constraints-dev.txt
```

All dependencies have been installed:

- ✅ `openai` - OpenAI API client
- ✅ `pillow` - Screenshot capture
- ✅ `pyautogui` - Mouse automation
- ✅ `keyboard` - Keyboard automation
- ✅ `screeninfo` - Multi-monitor detection

---

## 🚀 NEW FEATURES: Selective Region Monitoring

To reduce API costs and screenshot size, you can now:

1. **Monitor specific screens only** (e.g., left and right, skip middle)
2. **Capture only quadrants** (e.g., bottom-left where the approval button appears)

### Why This Matters

**Full desktop capture (3 monitors, 1920x1080 each):**

- Screenshot size: ~16 MB
- Cost: Higher per API call

**Selective capture (2 monitors, bottom-left quadrant):**

- Screenshot size: ~2 MB (8x smaller!)
- Cost: Significantly lower

---

## 📋 Usage Examples

### Setup: Set Your API Key

```powershell
# One-time setup (persists across sessions)
$env:OPENAI_API_KEY = "sk-your-api-key-here"
```

### 1. Full Desktop Capture (Default)

```powershell
# Dry run test
python -m automation.desktop_auto_allow_agent --dry-run --once

# Live run
python -m automation.desktop_auto_allow_agent
```

### 2. Monitor Specific Screens Only

**You have 3 monitors, only want to monitor left (0) and right (2):**

```powershell
# Dry run test
python -m automation.desktop_auto_allow_agent --dry-run --once --monitors 0,2

# Live run
python -m automation.desktop_auto_allow_agent --monitors 0,2
```

### 3. Capture Bottom-Left Quadrant Only

**Since approval buttons are always in the bottom-left quadrant:**

```powershell
# Dry run test
python -m automation.desktop_auto_allow_agent --dry-run --once --quadrant bottom-left

# Live run
python -m automation.desktop_auto_allow_agent --quadrant bottom-left
```

### 4. Combined: Specific Monitors + Quadrant (Recommended!)

**Monitor left and right screens, only bottom-left quadrant:**

```powershell
# Dry run test
python -m automation.desktop_auto_allow_agent --dry-run --once --monitors 0,2 --quadrant bottom-left

# Live run - most cost-effective!
python -m automation.desktop_auto_allow_agent --monitors 0,2 --quadrant bottom-left --interval 90
```

---

## 🎯 Recommended Configuration for Your Setup

Based on your requirements:

- 3 monitors (left, middle, right)
- Only monitor left and right
- Approval button always in bottom-left quadrant

**Optimal command:**

```powershell
python -m automation.desktop_auto_allow_agent `
  --monitors 0,2 `
  --quadrant bottom-left `
  --interval 90 `
  --dry-run
```

This will:

- ✅ Only capture monitors 0 and 2 (left and right)
- ✅ Only capture bottom-left quadrant of each (~1/4 of full size)
- ✅ Check every 90 seconds (vs default 60)
- ✅ Significantly reduce API costs
- ✅ Maintain full accuracy (button is always in that quadrant)

**When ready, remove `--dry-run` to run live:**

```powershell
python -m automation.desktop_auto_allow_agent `
  --monitors 0,2 `
  --quadrant bottom-left `
  --interval 90
```

---

## 🔍 How Coordinate Mapping Works

The agent automatically handles coordinate translation:

1. **Screenshot captured**: Bottom-left quadrant of monitors 0 and 2
2. **Model detects button**: Returns coordinates in screenshot space (e.g., x=150, y=200)
3. **Agent maps to desktop**: Converts to actual desktop coordinates considering:
   - Monitor position offsets
   - Quadrant offsets
   - Multi-monitor stitching
4. **Click executed**: At the correct desktop location

**Example:**

```
Screenshot: Click at (150, 200) in bottom-left quadrant
↓
Desktop: Click at (150, 1080 + 200) = (150, 1280)
```

---

## 📊 Cost Comparison

| Configuration                  | Screenshot Size | Monitors | Reduction       | Recommended For          |
| ------------------------------ | --------------- | -------- | --------------- | ------------------------ |
| Full desktop (3 monitors)      | ~16 MB          | All 3    | Baseline        | Testing only             |
| Two monitors only              | ~11 MB          | 0, 2     | 31% smaller     | Basic setup              |
| Full + bottom-left quadrant    | ~4 MB           | All 3    | 75% smaller     | If middle monitor needed |
| **Two monitors + bottom-left** | **~2 MB**       | **0, 2** | **87% smaller** | **Best for your setup**  |

---

## 🧪 Testing Workflow

### Step 1: Verify Monitor Detection

```powershell
# Test without API key to see how regions are detected
python -c "from automation.desktop_auto_allow_agent import AutoAllowAgent; import os; os.environ['OPENAI_API_KEY']='test'; agent=AutoAllowAgent(); print('Regions:', agent.get_monitor_regions())"
```

### Step 2: Test Screenshot Capture (Dry Run)

```powershell
python -m automation.desktop_auto_allow_agent --dry-run --once --monitors 0,2 --quadrant bottom-left
```

Expected output:

```
[2025-11-22 XX:XX:XX] Capturing 2 monitor region(s), quadrant: bottom-left
[2025-11-22 XX:XX:XX] Calling OpenAI Computer Use API...
[2025-11-22 XX:XX:XX] Error calling OpenAI API: ...
Status: NO_BUTTON
```

### Step 3: Set Real API Key and Test

```powershell
$env:OPENAI_API_KEY = "sk-your-real-key"
python -m automation.desktop_auto_allow_agent --dry-run --once --monitors 0,2 --quadrant bottom-left
```

### Step 4: Go Live!

```powershell
python -m automation.desktop_auto_allow_agent --monitors 0,2 --quadrant bottom-left --interval 90
```

---

## 📝 All Available Options

```powershell
python -m automation.desktop_auto_allow_agent [OPTIONS]

Options:
  --dry-run              Don't actually click, just log what would happen
  --once                 Run once and exit (for testing)
  --interval N           Seconds between checks (default: 60)
  --rate-limit-cooldown N  Seconds to wait after rate limit (default: 1200)
  --monitors X,Y,Z       Comma-separated monitor indices (e.g., '0,2')
  --quadrant QUADRANT    Capture only specified quadrant:
                         - bottom-left
                         - bottom-right
                         - top-left
                         - top-right
```

---

## 💡 Tips

1. **Start with `--dry-run`** to verify detection without clicking
2. **Use `--once`** for quick tests
3. **Increase `--interval`** to reduce API costs (e.g., 120 or 180 seconds)
4. **Monitor logs** in `automation/auto_allow.log`
5. **Set longer intervals** during low-activity periods

---

## 🐛 Troubleshooting

### "Error: OpenAI API key required"

```powershell
$env:OPENAI_API_KEY = "sk-your-key-here"
```

### Coordinates are off

- Verify monitor indices with `screeninfo` library
- Check log for "screenshot -> desktop" coordinate mappings
- Test with `--dry-run` to see coordinate translation

### Not detecting button

- Try without `--quadrant` first to verify button is visible
- Check if button is actually in the bottom-left quadrant
- Review logs for detection status

---

## 📄 Log Files

All activity is logged to: `automation/auto_allow.log`

View logs:

```powershell
# See last 20 lines
Get-Content automation\auto_allow.log -Tail 20

# Watch in real-time
Get-Content automation\auto_allow.log -Tail 20 -Wait
```

---

## 🎉 Ready to Use!

Your recommended command for production:

```powershell
python -m automation.desktop_auto_allow_agent `
  --monitors 0,2 `
  --quadrant bottom-left `
  --interval 90
```

Press **Ctrl+C** to stop the agent at any time.
