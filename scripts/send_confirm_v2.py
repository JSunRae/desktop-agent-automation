"""
Send confirmation message to finished panel using panel_tracker functions
"""
import sys
import time
from pathlib import Path

import uiautomation as auto
import pyperclip

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.panel_tracker import (
    detect_panel_running_state,
    detect_panel_state_detailed,
)

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

def find_all_vscode_windows(timeout: float = 0.5) -> list:
    """Find ALL VS Code windows by title suffix."""
    vscode_windows = []
    try:
        for w in auto.GetRootControl().GetChildren():
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(timeout):
                            vscode_windows.append(w)
                except Exception:
                    continue
    except Exception as e:
        print(f"  Warning: UI enumeration error: {e}")
    return vscode_windows

def main():
    print("=" * 60)
    print("SEND CONFIRMATION TO FINISHED PANEL")
    print("=" * 60)
    
    windows = find_all_vscode_windows()
    print(f"\nFound {len(windows)} VS Code window(s)")
    
    if not windows:
        print("\nNo VS Code windows found!")
        return
    
    finished_window = None
    send_button = None
    
    for win in windows:
        title = (win.Name or "")[:50] + "..."
        
        # Use panel tracker to get state
        is_running = detect_panel_running_state(win)
        detailed = detect_panel_state_detailed(win)
        has_send = detailed.get("has_send_button", False)
        
        print(f"\n{title}")
        print(f"  Is Running: {is_running}, Has Send: {has_send}")
        
        # Get the actual send button control if needed
        btn = None
        if has_send:
            try:
                btn = win.ButtonControl(searchDepth=15, Name='Send')
                if not btn.Exists(maxSearchSeconds=0.3):
                    btn = None
            except Exception:
                pass
        
        if has_send and not is_running:
            finished_window = win
            send_button = btn
            print("  >>> SELECTED - This is the finished panel")
    
    if not finished_window:
        print("\nNo finished panel found!")
        return
    
    # Send message
    message = 'If you are finished, confirm with "finished".'
    print(f"\n" + "-" * 60)
    print(f"Sending: {message}")
    print("-" * 60)
    
    finished_window.SetFocus()
    time.sleep(0.4)
    
    # Focus chat input
    auto.SendKeys('{Ctrl}l', interval=0.05)
    time.sleep(0.3)
    
    # Paste message
    pyperclip.copy(message)
    auto.SendKeys('{Ctrl}a', interval=0.05)
    time.sleep(0.1)
    auto.SendKeys('{Ctrl}v', interval=0.05)
    time.sleep(0.3)
    
    # Click Send
    try:
        send_button.Click()
        print("\n✓ Message sent!")
    except Exception as e:
        print(f"Error: {e}")
        auto.SendKeys('{Ctrl}{Enter}', interval=0.05)
        print("✓ Sent via Ctrl+Enter")

if __name__ == "__main__":
    main()
