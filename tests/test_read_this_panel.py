"""
Read text from the CURRENT/ACTIVE panel's input box.
Uses clipboard method: Focus input -> Ctrl+A -> Ctrl+C
"""
import uiautomation as auto
import time
import pyperclip

def find_vscode_windows():
    """Find all VS Code windows."""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        if win.ControlTypeName == "WindowControl":
            name = win.Name or ""
            if "Visual Studio Code" in name:
                windows.append(win)
    return windows

def get_panel_state(window):
    """Detect if panel is RUNNING (Cancel) or IDLE (Send)."""
    try:
        # Look for Cancel button (running) or Send button (idle)
        cancel = window.ButtonControl(searchDepth=15, Name="Cancel (Escape)", searchInterval=0.1, timeout=0.5)
        if cancel.Exists(0, 0):
            rect = cancel.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                return "RUNNING", cancel
    except:
        pass
    
    try:
        send = window.ButtonControl(searchDepth=15, Name="Send (Enter)", searchInterval=0.1, timeout=0.5)
        if send.Exists(0, 0):
            rect = send.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                return "IDLE", send
    except:
        pass
    
    return "UNKNOWN", None

def read_input_via_clipboard(window):
    """Read input text by focusing and using clipboard."""
    # Clear clipboard first
    pyperclip.copy("")
    
    # Focus the window
    window.SetFocus()
    time.sleep(0.3)
    
    # Use Ctrl+L to focus chat input
    auto.SendKeys("{Ctrl}l")
    time.sleep(0.2)
    
    # Select all and copy
    auto.SendKeys("{Ctrl}a")
    time.sleep(0.1)
    auto.SendKeys("{Ctrl}c")
    time.sleep(0.2)
    
    # Get clipboard content
    content = pyperclip.paste()
    return content

def main():
    print("=" * 60)
    print("Reading text from THIS panel's input box")
    print("=" * 60)
    
    windows = find_vscode_windows()
    print(f"\nFound {len(windows)} VS Code windows")
    
    # Find the RUNNING panel (this conversation)
    for i, win in enumerate(windows):
        name = win.Name or "(no name)"
        short_name = name[:50] + "..." if len(name) > 50 else name
        
        state, button = get_panel_state(win)
        print(f"\nWindow {i+1}: {short_name}")
        print(f"  State: {state}")
        
        if state == "RUNNING":
            print(f"\n  → This is a RUNNING panel - reading input...")
            
            content = read_input_via_clipboard(win)
            
            print("\n  Input text content:")
            print("-" * 50)
            if content:
                print(content)
            else:
                print("(empty)")
            print("-" * 50)
            
            # Check for specific text
            if "yes" in content.lower():
                print("\n  ✓ Found 'yes' in input!")
            if content.strip():
                print(f"\n  Content length: {len(content)} chars")
            
            return  # Stop after first running panel
    
    print("\nNo RUNNING panels found!")

if __name__ == "__main__":
    main()
