"""
Read-only test - just observe the active panel without clicking anything
"""
import uiautomation as auto
import time

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

def get_vscode_windows():
    """Get all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name
            if name and name.endswith(VSCODE_TITLE_SUFFIX):
                windows.append(win)
        except:
            pass
    return windows

def read_panel_content(window):
    """Read the chat panel content without clicking anything"""
    try:
        # Find the chat panel document
        chat_doc = window.DocumentControl(searchDepth=15, Name="Chat")
        if chat_doc.Exists(0, 0):
            # Try to get text via ValuePattern
            value_pattern = chat_doc.GetValuePattern()
            if value_pattern:
                text = value_pattern.Value
                return text if text else "(ValuePattern returned empty)"
            return "(No ValuePattern)"
        return "(No Chat document found)"
    except Exception as e:
        return f"(Error: {e})"

def check_buttons(window):
    """Check what buttons are visible without clicking"""
    buttons_found = []
    try:
        # Look for common buttons
        for btn_name in ["Cancel", "Send", "Allow", "Keep Edits"]:
            btn = window.ButtonControl(searchDepth=15, Name=btn_name)
            if btn.Exists(0, 0):
                rect = btn.BoundingRectangle
                buttons_found.append(f"{btn_name} @ ({rect.left},{rect.top},{rect.right},{rect.bottom})")
    except Exception as e:
        buttons_found.append(f"Error: {e}")
    return buttons_found

def get_visible_text_controls(window):
    """Get text from visible controls without clicking"""
    texts = []
    try:
        # Look for text controls in the window
        for text_ctrl in window.GetChildren():
            try:
                if text_ctrl.Name and len(text_ctrl.Name) > 0:
                    texts.append(f"[{text_ctrl.ControlTypeName}] {text_ctrl.Name[:100]}")
            except:
                pass
    except:
        pass
    return texts

print("=" * 60)
print("READ-ONLY PANEL OBSERVATION")
print("=" * 60)

windows = get_vscode_windows()
print(f"\nFound {len(windows)} VS Code windows\n")

for i, win in enumerate(windows):
    title = win.Name[:60] + "..." if len(win.Name) > 60 else win.Name
    print(f"\n{'='*60}")
    print(f"Window {i+1}: {title}")
    print("=" * 60)
    
    # Check buttons
    buttons = check_buttons(win)
    print(f"\nVisible buttons: {buttons if buttons else 'None found'}")
    
    # Read panel content (no clicks!)
    content = read_panel_content(win)
    print(f"\nChat content via ValuePattern:")
    if content:
        # Show last 500 chars
        if len(content) > 500:
            print(f"  ...{content[-500:]}")
        else:
            print(f"  {content}")
    
    # Check if this is the active/focused window
    is_focused = False
    try:
        focused = auto.GetFocusedControl()
        if focused:
            # Walk up to find if this window contains the focused control
            parent = focused.GetParentControl()
            while parent:
                if parent == win:
                    is_focused = True
                    break
                parent = parent.GetParentControl()
    except:
        pass
    
    print(f"\nIs focused/active: {is_focused}")

print("\n" + "=" * 60)
print("Done - no clicks or interactions were performed")
print("=" * 60)
