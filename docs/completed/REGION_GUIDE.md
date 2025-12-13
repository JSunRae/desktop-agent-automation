# Region Monitoring - Visual Guide

## Your Multi-Monitor Setup

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│                 │  │                 │  │                 │
│   Monitor 0     │  │   Monitor 1     │  │   Monitor 2     │
│   (Left)        │  │   (Middle)      │  │   (Right)       │
│                 │  │                 │  │                 │
│   1920x1080     │  │   1920x1080     │  │   1920x1080     │
│                 │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
     MONITOR              MONITOR              MONITOR
        ↓                    ↓                    ↓
  Monitor Index 0      Monitor Index 1      Monitor Index 2
```

---

## Scenario 1: Full Desktop Capture (Default)

**Command:** `python -m automation.desktop_auto_allow_agent`

```
┌──────────────────────────────────────────────────────────────┐
│ ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐│
│ │█████████████████│  │█████████████████│  │█████████████████││
│ │█████████████████│  │█████████████████│  │█████████████████││
│ │████Monitor 0████│  │████Monitor 1████│  │████Monitor 2████││
│ │█████████████████│  │█████████████████│  │█████████████████││
│ │█████████████████│  │█████████████████│  │█████████████████││
│ └─────────────────┘  └─────────────────┘  └─────────────────┘│
└──────────────────────────────────────────────────────────────┘
  All 3 monitors captured | Screenshot: ~16 MB
```

---

## Scenario 2: Selective Monitors (Your Need)

**Command:** `--monitors 0,2`

```
┌──────────────────────────────────────────────────────────────┐
│ ┌─────────────────┐                      ┌─────────────────┐│
│ │█████████████████│                      │█████████████████││
│ │█████████████████│        [SKIP]        │█████████████████││
│ │████Monitor 0████│                      │████Monitor 2████││
│ │█████████████████│                      │█████████████████││
│ │█████████████████│                      │█████████████████││
│ └─────────────────┘                      └─────────────────┘│
└──────────────────────────────────────────────────────────────┘
  Only monitors 0 and 2 | Screenshot: ~11 MB (31% reduction)
```

---

## Scenario 3: Quadrant Capture (Cost Optimized)

**Command:** `--quadrant bottom-left`

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│         │       │  │         │       │  │         │       │
│  [skip] │[skip] │  │  [skip] │[skip] │  │  [skip] │[skip] │
│─────────┼───────│  │─────────┼───────│  │─────────┼───────│
│ ████████│[skip] │  │ ████████│[skip] │  │ ████████│[skip] │
│ ████████│       │  │ ████████│       │  │ ████████│       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
    Monitor 0            Monitor 1            Monitor 2
     
All 3 monitors, bottom-left only | Screenshot: ~4 MB (75% reduction)
```

---

## Scenario 4: RECOMMENDED - Selective + Quadrant

**Command:** `--monitors 0,2 --quadrant bottom-left`

```
┌─────────────────┐                      ┌─────────────────┐
│         │       │                      │         │       │
│  [skip] │[skip] │        [SKIP]        │  [skip] │[skip] │
│─────────┼───────│                      │─────────┼───────│
│ ████████│[skip] │                      │ ████████│[skip] │
│ ████████│       │                      │ ████████│       │
└─────────────────┘                      └─────────────────┘
    Monitor 0                                Monitor 2
     
Only monitors 0,2, bottom-left only | Screenshot: ~2 MB (87% reduction!)
```

---

## Quadrant Layout

Each monitor is divided into 4 quadrants:

```
┌─────────────────────┐
│          │          │
│ top-left │top-right │
│          │          │
├──────────┼──────────┤
│          │          │
│bottom-   │ bottom-  │
│ left ★   │  right   │
│          │          │
└─────────────────────┘

★ = Where Copilot approval buttons appear
```

---

## Screenshot Stitching (Multiple Monitors)

When you specify `--monitors 0,2`, the agent stitches them vertically:

```
Captured Screenshot:
┌─────────────────┐
│                 │
│   Monitor 0     │ ← y: 0 to 539
│ (bottom-left)   │
│                 │
├─────────────────┤
│                 │
│   Monitor 2     │ ← y: 540 to 1079
│ (bottom-left)   │
│                 │
└─────────────────┘

Screenshot dimensions: 960x1080 (2 quadrants stacked)
```

---

## Coordinate Mapping Example

**Scenario:** Button detected at screenshot coordinates (150, 600)

### Without Regions (Full Desktop)
```
Screenshot (150, 600) → Desktop (150, 600)
                        Direct mapping
```

### With Monitors 0,2 + Bottom-Left Quadrant
```
Screenshot (150, 600)
    ↓
In monitor 2's region (y > 540)
    ↓
Offset by Monitor 0 height: 600 - 540 = 60 (local y in Monitor 2)
    ↓
Apply quadrant offset: bottom-left starts at y = 540 within monitor
    ↓
Add Monitor 2's desktop position: x = 3840 (if monitors are side-by-side)
    ↓
Desktop coordinates: (3840 + 150, 1080/2 + 60) = (3990, 600)
```

The agent handles all this automatically! ✨

---

## API Cost Comparison

| Configuration | Size | API Calls/Hour | Est. Cost/Day* |
|---------------|------|----------------|----------------|
| Full (3 monitors) | 16 MB | 60 | $$$ |
| 2 monitors | 11 MB | 60 | $$ |
| Full + quadrant | 4 MB | 60 | $ |
| **2 monitors + quadrant (90s)** | **2 MB** | **40** | **$** |

*Approximate - actual costs depend on OpenAI pricing and usage

---

## Testing Your Configuration

### Step 1: Identify Your Monitors

```powershell
python -c "from screeninfo import get_monitors; [print(f'Monitor {i}: {m}') for i, m in enumerate(get_monitors())]"
```

Expected output:
```
Monitor 0: Monitor(x=0, y=0, width=1920, height=1080, ...)
Monitor 1: Monitor(x=1920, y=0, width=1920, height=1080, ...)
Monitor 2: Monitor(x=3840, y=0, width=1920, height=1080, ...)
```

### Step 2: Test Region Capture (Dry Run)

```powershell
# Full desktop
python -m automation.desktop_auto_allow_agent --dry-run --once

# Left and right monitors only
python -m automation.desktop_auto_allow_agent --dry-run --once --monitors 0,2

# Left and right, bottom-left quadrant
python -m automation.desktop_auto_allow_agent --dry-run --once --monitors 0,2 --quadrant bottom-left
```

### Step 3: Check Logs

```powershell
Get-Content automation\auto_allow.log -Tail 5
```

Look for:
```
[2025-11-22 XX:XX:XX] Capturing 2 monitor region(s), quadrant: bottom-left
[2025-11-22 XX:XX:XX] Calling OpenAI Computer Use API...
```

---

## When to Use Each Configuration

### Use Full Desktop If:
- Testing initial setup
- Button location unknown
- Single monitor setup

### Use Selective Monitors If:
- You know which screens have VS Code
- Middle monitor never shows approval buttons
- Want to reduce cost by ~30%

### Use Quadrant Capture If:
- Button location is predictable
- Want to significantly reduce costs (~75%)
- Have confirmed button is always in same quadrant

### Use Selective + Quadrant If: ⭐ RECOMMENDED
- You want optimal cost savings (~87%)
- Button always appears in bottom-left of specific monitors
- This is your production configuration!

---

## Production Recommendation

For your setup (3 monitors, approval in bottom-left of left/right screens):

```powershell
python -m automation.desktop_auto_allow_agent `
  --monitors 0,2 `
  --quadrant bottom-left `
  --interval 90 `
  2>&1 | Tee-Object -FilePath automation\run.log
```

This configuration:
- ✅ 87% smaller screenshots
- ✅ ~40 API calls/hour (vs 60)
- ✅ Captures exact region where buttons appear
- ✅ Logs to both console and file
- ✅ Most cost-effective solution

Press **Ctrl+C** to stop.
