# Panel Alignment Fixes - December 12, 2025

## Issues Resolved

### 1. Z-Order Problem: Panels Behind Windows

**Problem**: Panels were sometimes appearing behind the main VS Code window or behind other panels after alignment, making them invisible or hard to access.

**Root Cause**: The `SetWindowPos` function was using `SWP_NOZORDER` flag, which preserves the existing Z-order (stacking order) of windows. When a panel was already behind other windows before alignment, it remained behind them even after being moved to the correct position.

**Fix**: Changed from using `SWP_NOZORDER` to using `HWND_TOP` (value `0`) as the `hwndInsertAfter` parameter. This places windows at the top of the Z-order (but not "topmost" - they can still be covered by user interaction).

**Code Changes** (`scripts/align_panels.py`):
```python
# BEFORE (problematic):
flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER
win32gui.SetWindowPos(hwnd, 0, position.x, position.y, position.width, position.height, flags)

# AFTER (fixed):
HWND_TOP = 0
flags = win32con.SWP_NOACTIVATE  # Removed SWP_NOZORDER
win32gui.SetWindowPos(hwnd, HWND_TOP, position.x, position.y, position.width, position.height, flags)
```

**Result**: Panels are now visible after alignment and properly positioned in front of other windows.

---

### 2. Multi-Desktop Support

**Problem**: The script only aligned panels on a single desktop specified by `--desktop` flag, requiring manual runs for each virtual desktop.

**Enhancement**: Added `--all-desktops` flag to automatically align panels across all virtual desktops in one run.

**Usage**:
```powershell
# Align panels on all virtual desktops
python scripts/align_panels.py --all-desktops

# Align panels on specific desktop (original behavior)
python scripts/align_panels.py --desktop TF
```

**How it Works**:
1. When `--all-desktops` is specified, the script uses `pyvda` to enumerate all virtual desktops
2. For each desktop:
   - Switches to that desktop
   - Finds VS Code windows
   - Loads or creates appropriate layout
   - Aligns panels
   - Reports results
3. Shows summary of total results across all desktops

**Example Output**:
```
================================================================================
Processing desktop: TF
================================================================================

Scanning for VS Code windows...
Found 13 VS Code window(s)

Looking for layout: 2560x1440_13
✅ Found matching layout for 13 panels on 2560x1440
Loaded 13 layout configuration(s)

↻ Aligning: Chat 11 - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code
  From: (1706, 0) 426x455
  To:   (852, 910) 426x490

Desktop 'TF' results: 2 aligned, 22 skipped

================================================================================
Processing desktop: Trading
================================================================================

...

================================================================================
TOTAL RESULTS across 3 desktops:
Results: 5 aligned, 38 skipped
================================================================================
```

---

## Technical Details

### Window Z-Order Hierarchy

Windows maintains a Z-order (depth) for all windows on the desktop:
- **HWND_TOPMOST** (-1): Always on top of all other windows
- **HWND_TOP** (0): Top of normal windows (can be covered by topmost)
- **HWND_NOTOPMOST** (-2): Below topmost windows
- **HWND_BOTTOM** (1): Bottom of Z-order

The `SWP_NOZORDER` flag tells Windows to ignore the `hwndInsertAfter` parameter and keep the current Z-order unchanged. This is usually desired for background operations, but in our case, it caused panels to remain hidden.

### SetWindowPos Flags

- **SWP_NOACTIVATE**: Don't activate (give focus to) the window - prevents stealing focus
- **SWP_NOZORDER**: Don't change Z-order - **REMOVED** to fix visibility issue
- **SWP_NOMOVE**: Don't move the window
- **SWP_NOSIZE**: Don't resize the window

### Virtual Desktop Switching

Uses `pyvda` library for reliable desktop switching by name:
- `pyvda.get_virtual_desktops()`: Get all desktops
- `desktop.name`: Get desktop name
- `desktop.go()`: Switch to desktop
- `VirtualDesktop.current()`: Get current desktop

---

## Testing

To test the fixes:

1. **Z-Order Fix Test**:
   ```powershell
   # Arrange some panels manually, ensuring some are behind the main window
   # Then run alignment
   python scripts/align_panels.py --desktop TF
   
   # Expected: All panels should be visible after alignment
   ```

2. **Multi-Desktop Test**:
   ```powershell
   # Ensure you have multiple virtual desktops with VS Code windows
   python scripts/align_panels.py --all-desktops
   
   # Expected: All desktops processed, panels aligned on each
   ```

3. **Dry Run Test**:
   ```powershell
   # Preview changes without applying
   python scripts/align_panels.py --all-desktops --dry-run
   
   # Expected: Shows what would be changed without actually moving windows
   ```

---

## Recommendations

1. **Use `--all-desktops` by default**: Add to your workflow scripts or aliases to align all desktops at once

2. **Monitor the output**: Check for "skipped" panels - these might need layout configurations

3. **Optimize per desktop**: Run `--optimize` on each desktop to create perfect layouts:
   ```powershell
   python scripts/align_panels.py --desktop TF --optimize
   ```

4. **Backup layouts**: The layout configurations are stored in `automation/panel_layout.json` - back this up

---

## Related Files

- `scripts/align_panels.py` - Main alignment script (fixed)
- `automation/panel_layout.json` - Panel layout configurations  
- `automation/desktop/switcher.py` - Desktop switching logic
- `docs/PANEL_ALIGNMENT.md` - Original documentation

---

## Future Enhancements

Potential improvements for consideration:

1. **Smart Z-ordering**: Instead of placing all panels at top, intelligently arrange them (main window at bottom, panels on top)

2. **Per-desktop optimization**: Automatically run `--optimize` when aligning all desktops

3. **Layout templates**: Pre-defined layouts for common configurations (3 panels, 5 panels, 13 panels, etc.)

4. **Restore after DPI change**: Detect DPI scaling changes and auto-realign

5. **Conflict detection**: Warn when panel positions overlap

---

## Changelog

### 2025-12-12
- Fixed Z-order issue causing panels to appear behind other windows
- Added `--all-desktops` flag for multi-desktop alignment
- Improved documentation with technical details
