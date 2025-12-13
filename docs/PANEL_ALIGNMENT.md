# Panel Alignment Guide

> **Recent Updates (2025-12-12)**: Fixed Z-order issues causing panels to appear behind windows, added multi-desktop support. See [PANEL_ALIGNMENT_FIXES.md](PANEL_ALIGNMENT_FIXES.md) for details.

## Overview

The panel alignment script helps fix VS Code window layouts when Windows moves them around due to DPI scaling issues. VS Code windows are not DPI-aware per monitor in the same way as native WinUI apps, so Windows often repositions them, causing your carefully arranged panels to clump together.

## Quick Start

### 1. Configure Your Layout (One Time Setup)

First, arrange your VS Code windows exactly how you want them. Then capture this layout:

```powershell
# Capture current layout as "default" configuration
python scripts/align_panels.py --configure

# Or capture for a specific desktop
python scripts/align_panels.py --configure --desktop TF
```

This will:
- Detect all your VS Code windows
- Show you each window and ask for a pattern to identify it
- Save the positions to `automation/panel_layout.json`

### 2. Realign Panels

When Windows moves your panels around, just run:

```powershell
# Align panels on current desktop
python scripts/align_panels.py

# Align panels on specific desktop
python scripts/align_panels.py --desktop TF

# Align panels on ALL virtual desktops (recommended)
python scripts/align_panels.py --all-desktops

# Preview changes without applying (dry run)
python scripts/align_panels.py --dry-run
```

### 3. Advanced Options

```powershell
# Optimize current layout (learns from your arrangement)
python scripts/align_panels.py --desktop TF --optimize

# Auto-create grid layout
python scripts/align_panels.py --auto-grid

# Smart pack layout (preserves sizes)
python scripts/align_panels.py --smart-pack
```

## How It Works

### Pattern Matching

The script uses pattern matching to identify which window should go where. For example:

- Pattern: `"Priority: P1"` matches any window with "Priority: P1" in the title
- Pattern: `"tf_1"` matches windows like `"Priority: P2 - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code"`
- Pattern: `"Trading"` matches windows like `"You are assigned task: manifest… - Trading - Visual Studio Code"`

### Monitor-Relative Positioning

Positions are stored relative to each monitor's top-left corner. This means:
- On Monitor 0 (primary), position (0, 0) is the top-left of that monitor
- On Monitor 1 (secondary), position (0, 0) is the top-left of Monitor 1
- The script automatically adds the monitor offset when positioning windows

### Configuration File

The configuration is stored in `automation/panel_layout.json`:

```json
{
  "default": [
    {
      "pattern": "Trading",
      "position": {
        "x": 0,
        "y": 0,
        "width": 1920,
        "height": 1080
      },
      "monitor_index": 0
    }
  ],
  "TF": [
    {
      "pattern": "Priority: P1",
      "position": {
        "x": 0,
        "y": 0,
        "width": 960,
        "height": 1080
      },
      "monitor_index": 0
    }
  ]
}
```

## Usage Examples

### Basic Usage

```powershell
# Align all panels using default configuration
python scripts/align_panels.py

# See what would change without actually moving windows
python scripts/align_panels.py --dry-run
```

### Desktop-Specific Layouts

```powershell
# Configure layout for "TF" desktop
python scripts/align_panels.py --configure --desktop TF

# Configure layout for "Trading" desktop
python scripts/align_panels.py --configure --desktop Trading

# Apply the "TF" desktop layout
python scripts/align_panels.py --desktop TF

# Apply the "Trading" desktop layout
python scripts/align_panels.py --desktop Trading
```

### Named Configurations

You can have multiple configurations independent of desktop names:

```powershell
# Save current layout as "morning_setup"
python scripts/align_panels.py --configure --config-name morning_setup

# Save current layout as "evening_setup"
python scripts/align_panels.py --configure --config-name evening_setup

# Apply morning setup
python scripts/align_panels.py --config-name morning_setup

# Apply evening setup
python scripts/align_panels.py --config-name evening_setup
```

## Common Layouts

### Two-Column Layout (Single Monitor)

Perfect for two priority levels side-by-side:

```json
{
  "default": [
    {
      "pattern": "Priority: P1",
      "position": {"x": 0, "y": 0, "width": 960, "height": 1080},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P2",
      "position": {"x": 960, "y": 0, "width": 960, "height": 1080},
      "monitor_index": 0
    }
  ]
}
```

### Quad Layout (2x2 Grid)

Four panels in a grid:

```json
{
  "default": [
    {
      "pattern": "P1",
      "position": {"x": 0, "y": 0, "width": 960, "height": 540},
      "monitor_index": 0
    },
    {
      "pattern": "P2",
      "position": {"x": 960, "y": 0, "width": 960, "height": 540},
      "monitor_index": 0
    },
    {
      "pattern": "P3",
      "position": {"x": 0, "y": 540, "width": 960, "height": 540},
      "monitor_index": 0
    },
    {
      "pattern": "P4",
      "position": {"x": 960, "y": 540, "width": 960, "height": 540},
      "monitor_index": 0
    }
  ]
}
```

### Multi-Monitor Setup

Different panels on different monitors:

```json
{
  "default": [
    {
      "pattern": "Trading",
      "position": {"x": 0, "y": 0, "width": 1920, "height": 1080},
      "monitor_index": 0
    },
    {
      "pattern": "tf_1",
      "position": {"x": 0, "y": 0, "width": 2560, "height": 1440},
      "monitor_index": 1
    }
  ]
}
```

### Seven-Panel Vertical Screen Layout

Perfect for vertical/portrait monitors with 7 agents stacked vertically:

```json
{
  "default": [
    {
      "pattern": "Priority: P1",
      "position": {"x": 0, "y": 0, "width": 1080, "height": 274},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P2",
      "position": {"x": 0, "y": 274, "width": 1080, "height": 274},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P3",
      "position": {"x": 0, "y": 548, "width": 1080, "height": 274},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P4",
      "position": {"x": 0, "y": 822, "width": 1080, "height": 274},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P5",
      "position": {"x": 0, "y": 1096, "width": 1080, "height": 274},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P6",
      "position": {"x": 0, "y": 1370, "width": 1080, "height": 274},
      "monitor_index": 0
    },
    {
      "pattern": "Priority: P7",
      "position": {"x": 0, "y": 1644, "width": 1080, "height": 276},
      "monitor_index": 0
    }
  ]
}
```

## Troubleshooting

### Windows Not Moving

1. Make sure `pywin32` is installed:
   ```powershell
   pip install pywin32
   ```

2. Check that windows aren't maximized (maximized windows can't be moved)

3. Run with `--dry-run` to see what would happen

### Pattern Not Matching

1. Run the script to see which windows are found
2. Check the window titles being displayed
3. Use a more specific or general pattern as needed

### Windows on Wrong Monitor

1. Run `--configure` again while windows are on correct monitors
2. Check the `monitor_index` values in your config file
3. Verify monitor detection with the initial output showing all monitors

### Positions Slightly Off

This is normal - the script has a 10-pixel tolerance to avoid unnecessary moves. If you need pixel-perfect alignment, you can adjust the `tolerance` value in the script.

## Integration with Automation

You can call this script from your automation to periodically realign panels:

```python
import subprocess

# Realign panels every hour
subprocess.run(["python", "scripts/align_panels.py", "--desktop", "TF"])
```

Or add it to your hotkeys in VS Code automation:

```python
# Add to automation/orchestrator.py
import subprocess

def realign_panels():
    """Realign all panels to configured positions."""
    subprocess.run(["python", "scripts/align_panels.py"])

# Register hotkey (e.g., Ctrl+Alt+A for align)
keyboard.add_hotkey('ctrl+alt+a', realign_panels)
```

## Advanced: Automatic Realignment

You can set up automatic realignment that runs periodically:

```python
# Add to your automation loop
import time
from datetime import datetime, timedelta

last_align = datetime.now()
REALIGN_INTERVAL_MINUTES = 30

while True:
    # ... existing automation code ...
    
    # Check if it's time to realign
    if datetime.now() - last_align > timedelta(minutes=REALIGN_INTERVAL_MINUTES):
        try:
            subprocess.run(["python", "scripts/align_panels.py"], 
                          capture_output=True, timeout=30)
            last_align = datetime.now()
        except Exception as e:
            print(f"Warning: Could not realign panels: {e}")
```

## Tips

1. **Start Simple**: Begin with a basic 2-column layout before moving to complex grids
2. **Use Descriptive Patterns**: Make patterns specific enough to match the right windows
3. **Test with Dry Run**: Always test with `--dry-run` before applying a new configuration
4. **Save Multiple Configs**: Create different configurations for different workflows
5. **Check Monitor Order**: Monitor indices may change if you disconnect/reconnect displays
