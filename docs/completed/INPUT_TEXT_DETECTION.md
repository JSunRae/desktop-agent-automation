# Input Text Detection Guide

## Overview

This document describes how to read text from VS Code Copilot chat input boxes using Windows UI Automation.

## The Challenge

VS Code's chat input uses Monaco editor, which:
- **Does NOT** expose text via standard UI Automation patterns (ValuePattern, TextPattern)
- **Requires focus** before text becomes accessible
- Uses a complex control hierarchy that's not intuitive to navigate

## Solution: Clipboard Method

The reliable method to read input text:

1. **Focus the window** - `vs_win.SetFocus()`
2. **Dismiss dialogs** - Press `Escape` to close any modal dialogs
3. **Focus chat input** - Press `Ctrl+L` (VS Code shortcut for chat focus)
4. **Select all** - Press `Ctrl+A`
5. **Copy** - Press `Ctrl+C`
6. **Read clipboard** - Use PowerShell `Get-Clipboard`
7. **Deselect** - Press `End` to move cursor without selection

## Code Example

```python
import uiautomation as auto
import subprocess
import time

def read_chat_input(vs_win):
    """Read text from VS Code Copilot chat input."""
    import ctypes
    
    original_window = ctypes.windll.user32.GetForegroundWindow()
    
    try:
        # Clear clipboard
        subprocess.run(
            ["powershell", "-Command", "Set-Clipboard -Value ''"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        # Focus window
        vs_win.SetFocus()
        time.sleep(0.3)
        
        # Dismiss dialogs
        auto.SendKeys("{Escape}")
        time.sleep(0.2)
        
        # Focus chat input
        auto.SendKeys("{Ctrl}l")
        time.sleep(0.2)
        
        # Select all and copy
        auto.SendKeys("{Ctrl}a")
        time.sleep(0.1)
        auto.SendKeys("{Ctrl}c")
        time.sleep(0.2)
        
        # Read clipboard
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        # Deselect
        auto.SendKeys("{End}")
        
        return result.stdout.strip() if result.returncode == 0 else ""
        
    finally:
        # Restore original window
        if original_window:
            time.sleep(0.1)
            ctypes.windll.user32.SetForegroundWindow(original_window)
```

## Panel State Detection

Detect if a panel is actively running or idle by looking for buttons:

| Button | State | Meaning |
|--------|-------|---------|
| `Cancel (Alt+Backspace)` | RUNNING | Agent is actively working |
| `Send` | IDLE | Ready for input or finished |

```python
def detect_panel_state(vs_win, max_depth=20):
    """Detect panel state by searching for Cancel or Send button."""
    found_cancel = False
    found_send = False
    
    def search(ctrl, depth=0):
        nonlocal found_cancel, found_send
        if depth > max_depth:
            return
        
        try:
            if ctrl.ControlTypeName == "ButtonControl":
                name = ctrl.Name or ""
                if "Cancel" in name:
                    found_cancel = True
                    return
                elif "Send" in name:
                    found_send = True
            
            for child in ctrl.GetChildren():
                search(child, depth + 1)
                if found_cancel:
                    return
        except:
            pass
    
    search(vs_win)
    
    if found_cancel:
        return "RUNNING"
    elif found_send:
        return "IDLE"
    return "UNKNOWN"
```

## Key VS Code Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+L` | Focus chat input |
| `Ctrl+A` | Select all text |
| `Ctrl+C` | Copy to clipboard |
| `Escape` | Dismiss dialog/cancel |
| `Alt+Backspace` | Cancel running agent |

## Common Issues

### "Start new chat?" Dialog
When Ctrl+L is pressed while another chat is active, VS Code may show a dialog asking about starting a new chat. This dialog captures the clipboard copy operation. Solution: Press Escape first.

### Window Focus
The script needs to focus the VS Code window, which temporarily steals focus from the terminal. Save and restore the original foreground window.

### Timing
Monaco editor needs time to respond to keyboard commands. Add small delays (0.1-0.3s) between operations.

## Files

- `automation/panel_input_reader.py` - Utility module for reading panel input
- `automation/panel_tracker.py` - Full panel tracking with state management
- `test_dismiss_and_read.py` - Test script that demonstrates the clipboard method

## Usage

```powershell
# List all panels and their states
python -m automation.panel_input_reader

# Read input from running panels
python -m automation.panel_input_reader --read-input

# Target specific window
python -m automation.panel_input_reader --window "my-project" --read-input
```
