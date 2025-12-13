"""
Robust send message to finished panel - uses multiple detection methods
"""
import uiautomation as auto
import time
import pyperclip
import subprocess

def get_vscode_windows():
    """Get VS Code windows using multiple methods"""
    windows = []
    
    # Method 1: GetRootControl children
    try:
        desktop = auto.GetRootControl()
        for child in desktop.GetChildren():
            try:
                if child.ControlType == auto.ControlType.WindowControl:
                    name = child.Name or ""
                    if 'Visual Studio Code' in name:
                        windows.append(child)
            except Exception:
                continue
    except Exception:
        pass
    
    if windows:
        return windows
    
    # Method 2: WindowControl search
    try:
        win = auto.WindowControl(searchDepth=1, SubName='Visual Studio Code')
        if win.Exists(maxSearchSeconds=1):
            windows.append(win)
            # Try to find more
            while True:
                next_win = win.GetNextSiblingControl()
                if not next_win or next_win.ControlType != auto.ControlType.WindowControl:
                    break
                if 'Visual Studio Code' in (next_win.Name or ''):
                    windows.append(next_win)
                win = next_win
    except Exception:
        pass
    
    if windows:
        return windows
    
    # Method 3: Find by class name
    try:
        win = auto.WindowControl(searchDepth=1, ClassName='Chrome_WidgetWin_1')
        while win.Exists(maxSearchSeconds=0.5):
            name = win.Name or ''
            if 'Visual Studio Code' in name:
                windows.append(win)
            try:
                win = win.GetNextSiblingControl()
                if not win:
                    break
            except Exception:
                break
    except Exception:
        pass
    
    return windows

def main():
    print("=" * 60)
    print("SEND MESSAGE TO FINISHED PANEL")
    print("=" * 60)
    
    # Add delay for window enumeration stability
    print("\nWaiting for UI stability...")
    time.sleep(1.5)
    
    windows = get_vscode_windows()
    print(f"\nFound {len(windows)} VS Code window(s)")
    
    if not windows:
        print("\nNo VS Code windows found!")
        print("Make sure VS Code windows are visible and not minimized.")
        return False
    
    # Find the finished panel (one with Send button visible, no Cancel)
    finished_window = None
    send_button = None
    
    for win in windows:
        title = (win.Name or "")[:60]
        print(f"\nChecking: {title}...")
        
        # Check for Cancel button (running)
        is_running = False
        try:
            cancel = win.ButtonControl(searchDepth=15, Name='Cancel')
            if cancel.Exists(maxSearchSeconds=0.3):
                rect = cancel.BoundingRectangle
                is_running = rect.width() > 0 and rect.height() > 0
        except Exception:
            pass
        
        # Check for Send button (finished)
        has_send = False
        btn = None
        try:
            btn = win.ButtonControl(searchDepth=15, Name='Send')
            if btn.Exists(maxSearchSeconds=0.3):
                rect = btn.BoundingRectangle
                has_send = rect.width() > 0 and rect.height() > 0
        except Exception:
            pass
        
        print(f"  Running: {is_running}, Has Send: {has_send}")
        
        if has_send and not is_running:
            finished_window = win
            send_button = btn
            print("  >>> This is the FINISHED panel!")
    
    if not finished_window:
        print("\nNo finished panel found (one with Send button but no Cancel).")
        return False
    
    # Send the message
    message = 'If you are finished, confirm with "finished".'
    print(f"\nSending message: {message}")
    
    # Focus window
    finished_window.SetFocus()
    time.sleep(0.4)
    
    # Focus chat input (Ctrl+L)
    auto.SendKeys('{Ctrl}l', interval=0.05)
    time.sleep(0.3)
    
    # Clear and paste
    pyperclip.copy(message)
    auto.SendKeys('{Ctrl}a', interval=0.05)
    time.sleep(0.1)
    auto.SendKeys('{Ctrl}v', interval=0.05)
    time.sleep(0.3)
    
    # Click Send
    try:
        send_button.Click()
        print("\n✓ Message sent successfully!")
        return True
    except Exception as e:
        print(f"\nError clicking Send: {e}")
        # Fallback to keyboard
        try:
            auto.SendKeys('{Ctrl}{Enter}', interval=0.05)
            print("✓ Message sent via Ctrl+Enter!")
            return True
        except Exception:
            return False

if __name__ == "__main__":
    success = main()
    print("\n" + "=" * 60)
    if success:
        print("COMPLETE - Message was sent to the finished panel")
    else:
        print("FAILED - Could not send message")
    print("=" * 60)
