# Panel Alignment Script - Summary

## What it does

Fixes VS Code window layouts when Windows moves them around due to DPI scaling issues.

## Key files created

1. **scripts/align_panels.py** - Main alignment script (576 lines)
   - Interactive configuration mode
   - Pattern-based window matching
   - Multi-monitor support
   - Dry-run mode for safe testing

2. **docs/PANEL_ALIGNMENT.md** - Complete documentation
   - Quick start guide
   - Common layouts (2-column, quad, multi-monitor)
   - Troubleshooting tips
   - Integration examples

3. **automation/panel_layout.json.example** - Example configuration
   - Shows desktop-specific layouts
   - Multi-monitor examples
   - Pattern matching examples

4. **tests/test_align_panels.py** - Unit tests
   - Tests all core functionality
   - All tests passing ✅

## How to use

### First time setup
```powershell
# Arrange your VS Code windows exactly how you want them
python scripts/align_panels.py --configure
```

### Realign panels
```powershell
# When Windows moves your panels around
python scripts/align_panels.py

# Or for a specific desktop
python scripts/align_panels.py --desktop TF
```

## Features

✅ Pattern matching to identify windows by title
✅ Multi-monitor support with relative positioning
✅ Desktop-specific configurations
✅ Dry-run mode to preview changes
✅ Interactive configuration with guided prompts
✅ Safe: 10-pixel tolerance to avoid unnecessary moves
✅ Uses Win32 API (SetWindowPos) for precise control

## Why this is useful

**Problem**: VS Code is not DPI-aware per monitor like native Windows apps. When you have multiple monitors with different DPI settings, Windows often repositions VS Code windows, causing your carefully arranged panels to clump together in the middle of your screens.

**Solution**: This script remembers where each window should be and puts it back when Windows moves it.

## Example configurations

### Two columns (P1 and P2 side-by-side)
```json
{
  "TF": [
    {"pattern": "Priority: P1", "position": {"x": 0, "y": 0, "width": 960, "height": 1080}},
    {"pattern": "Priority: P2", "position": {"x": 960, "y": 0, "width": 960, "height": 1080}}
  ]
}
```

### Multi-monitor setup
```json
{
  "default": [
    {"pattern": "Trading", "position": {"x": 0, "y": 0, "width": 1920, "height": 1080}, "monitor_index": 0},
    {"pattern": "tf_1", "position": {"x": 0, "y": 0, "width": 2560, "height": 1440}, "monitor_index": 1}
  ]
}
```

## Advanced usage

### Multiple named configurations
```powershell
python scripts/align_panels.py --configure --config-name morning_setup
python scripts/align_panels.py --config-name morning_setup
```

### Integration with automation
Add to your orchestrator to realign periodically:
```python
import subprocess
subprocess.run(["python", "scripts/align_panels.py"])
```

## Dependencies

- pywin32 (for SetWindowPos API)
- screeninfo (for monitor detection, optional)
- uiautomation (for finding VS Code windows)

All already in requirements.txt ✅

## Testing

Run the test suite:
```powershell
python tests/test_align_panels.py
```

All tests passing! ✅
