"""
Panel Input Reader - Utility for reading text from VS Code Copilot chat input boxes.

This module provides functions to:
- Detect panel state (RUNNING vs IDLE)
- Read text from the chat input box using clipboard method
- Find VS Code windows across the desktop

Key Findings:
- ValuePattern doesn't work for Monaco editor input boxes
- Focus is required before text is accessible
- Ctrl+L focuses the chat input in VS Code
- Clipboard method (Ctrl+A, Ctrl+C) is the most reliable way to read input
- Dialogs (like "Start new chat?") can interfere - use Escape first

Usage:
    from automation.panel_input_reader import (
        find_vscode_windows,
        detect_panel_state,
        read_chat_input,
        read_chat_input_safe
    )
    
    # Find all VS Code windows
    windows = find_vscode_windows()
    
    # Check panel state
    for win in windows:
        state = detect_panel_state(win)
        print(f"{win.Name}: {state}")
    
    # Read input from a specific window
    input_text = read_chat_input(windows[0])
    print(f"Input: {input_text}")
"""

from __future__ import annotations

import subprocess
import time
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import uiautomation as auto


class PanelState(Enum):
    """State of a Copilot chat panel."""
    RUNNING = "running"      # Cancel button visible - agent is actively working
    IDLE = "idle"           # Send button visible - ready for input
    UNKNOWN = "unknown"     # Neither button found


def find_vscode_windows() -> List["auto.Control"]:
    """
    Find all VS Code windows on the desktop.
    
    Returns:
        List of VS Code window controls
    """
    import uiautomation as auto
    
    windows = []
    root = auto.GetRootControl()
    
    for child in root.GetChildren():
        try:
            name = child.Name or ""
            class_name = child.ClassName or ""
            
            # VS Code windows have "Visual Studio Code" in title
            # or use the Chrome_WidgetWin_1 class
            if "Visual Studio Code" in name or class_name == "Chrome_WidgetWin_1":
                windows.append(child)
        except Exception:
            pass
    
    return windows


def find_vscode_window_by_title(title_fragment: str) -> Optional["auto.Control"]:
    """
    Find a VS Code window by title fragment.
    
    Args:
        title_fragment: Text to search for in window title
        
    Returns:
        The matching window control, or None
    """
    windows = find_vscode_windows()
    for win in windows:
        try:
            name = win.Name or ""
            if title_fragment.lower() in name.lower():
                return win
        except Exception:
            pass
    return None


def detect_panel_state(vs_win: "auto.Control", max_depth: int = 20, timeout: float = 5.0) -> PanelState:
    """
    Detect if a panel is RUNNING (Cancel button) or IDLE (Send button).
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum depth to search in control tree
        timeout: Maximum time to search (seconds)
        
    Returns:
        PanelState enum value
    """
    import uiautomation as auto
    
    start = time.time()
    found_cancel = False
    found_send = False
    
    def search(ctrl, depth=0):
        nonlocal found_cancel, found_send
        
        if time.time() - start > timeout:
            return
        if depth > max_depth:
            return
        
        try:
            ctrl_type = ctrl.ControlTypeName
            name = ctrl.Name or ""
            
            if ctrl_type == "ButtonControl":
                # Cancel button indicates RUNNING
                if "Cancel" in name:
                    found_cancel = True
                    return  # Found definitive state
                # Send button indicates IDLE
                elif "Send" in name and "Cancel" not in name:
                    found_send = True
            
            if found_cancel:
                return
                
            for child in ctrl.GetChildren():
                search(child, depth + 1)
                if found_cancel:
                    return
                    
        except Exception:
            pass
    
    search(vs_win)
    
    if found_cancel:
        return PanelState.RUNNING
    elif found_send:
        return PanelState.IDLE
    else:
        return PanelState.UNKNOWN


def read_chat_input(vs_win: "auto.Control") -> str:
    """
    Read the current text from the chat input box.
    
    Uses the clipboard method:
    1. Focus window
    2. Dismiss dialogs with Escape
    3. Focus chat input with Ctrl+L
    4. Select all with Ctrl+A
    5. Copy with Ctrl+C
    6. Read clipboard
    
    WARNING: This will focus the window and may interfere with user interaction.
    
    Args:
        vs_win: VS Code window control
        
    Returns:
        The input text, or empty string if none/error
    """
    import uiautomation as auto
    import ctypes
    
    try:
        original_window = ctypes.windll.user32.GetForegroundWindow()
        
        try:
            # Clear clipboard
            subprocess.run(
                ["powershell", "-Command", "Set-Clipboard -Value ''"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=2
            )
            
            # Focus window
            vs_win.SetFocus()
            time.sleep(0.3)
            
            # Dismiss any dialogs
            auto.SendKeys("{Escape}")
            time.sleep(0.2)
            
            # Focus chat input with Ctrl+L
            auto.SendKeys("{Ctrl}l")
            time.sleep(0.2)
            
            # Select all with Ctrl+A
            auto.SendKeys("{Ctrl}a")
            time.sleep(0.1)
            
            # Copy with Ctrl+C
            auto.SendKeys("{Ctrl}c")
            time.sleep(0.2)
            
            # Read clipboard
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=2
            )
            
            # Deselect
            auto.SendKeys("{End}")
            time.sleep(0.02)
            
            return result.stdout.strip() if result.returncode == 0 else ""
            
        finally:
            # Restore original window
            if original_window:
                time.sleep(0.1)
                ctypes.windll.user32.SetForegroundWindow(original_window)
                
    except Exception as e:
        print(f"Error reading chat input: {e}")
        return ""


def read_chat_input_safe(vs_win: "auto.Control") -> Optional[str]:
    """
    Safely read chat input - returns None if window cannot be accessed.
    
    Same as read_chat_input but catches all exceptions and returns None on failure.
    
    Args:
        vs_win: VS Code window control
        
    Returns:
        The input text, empty string if empty, or None on error
    """
    try:
        return read_chat_input(vs_win)
    except Exception:
        return None


def get_all_panel_states() -> List[dict]:
    """
    Get state information for all VS Code panels.
    
    Returns:
        List of dicts with window title and state
    """
    results = []
    
    for win in find_vscode_windows():
        try:
            name = win.Name or "Unknown"
            state = detect_panel_state(win)
            results.append({
                "title": name,
                "state": state.value,
                "control": win
            })
        except Exception as e:
            results.append({
                "title": "Error",
                "state": "error",
                "error": str(e)
            })
    
    return results


def read_input_from_all_running_panels() -> List[dict]:
    """
    Read input text from all RUNNING panels.
    
    WARNING: This focuses each window and may interfere with user interaction.
    
    Returns:
        List of dicts with window title, state, and input text
    """
    results = []
    
    for win in find_vscode_windows():
        try:
            name = win.Name or "Unknown"
            state = detect_panel_state(win)
            
            if state == PanelState.RUNNING:
                input_text = read_chat_input(win)
                results.append({
                    "title": name,
                    "state": state.value,
                    "input": input_text
                })
            else:
                results.append({
                    "title": name,
                    "state": state.value,
                    "input": None  # Not read for non-RUNNING panels
                })
                
        except Exception as e:
            results.append({
                "title": "Error",
                "state": "error",
                "error": str(e)
            })
    
    return results


# CLI for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Read VS Code Copilot panel states and inputs")
    parser.add_argument("--read-input", action="store_true", help="Read input from RUNNING panels")
    parser.add_argument("--window", type=str, help="Window title fragment to target")
    args = parser.parse_args()
    
    print("=" * 60)
    print("VS Code Panel State Reader")
    print("=" * 60)
    
    if args.window:
        # Target specific window
        win = find_vscode_window_by_title(args.window)
        if win:
            print(f"\nFound: {win.Name}")
            state = detect_panel_state(win)
            print(f"State: {state.value}")
            
            if args.read_input:
                print("\nReading input...")
                text = read_chat_input(win)
                print(f"Input: {text if text else '(empty)'}")
        else:
            print(f"\nNo window found matching: {args.window}")
    else:
        # List all panels
        panels = get_all_panel_states()
        print(f"\nFound {len(panels)} VS Code windows:")
        
        for i, panel in enumerate(panels, 1):
            print(f"\n  {i}. {panel['title'][:60]}")
            print(f"     State: {panel['state']}")
            
            if args.read_input and panel['state'] == 'running':
                text = read_chat_input(panel['control'])
                print(f"     Input: {text if text else '(empty)'}")
    
    print("\n" + "=" * 60)
