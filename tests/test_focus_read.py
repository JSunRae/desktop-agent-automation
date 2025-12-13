"""
Focus the idle panel's text input and read content via clipboard
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
        except Exception:
            pass
    return windows

def has_button(window, button_name, max_depth=20):
    """Check if window has a specific button"""
    def search(control, depth=0):
        if depth > max_depth:
            return None
        try:
            if control.ControlTypeName == "ButtonControl":
                if button_name in control.Name:
                    rect = control.BoundingRectangle
                    if rect.width() > 0 and rect.height() > 0:
                        return control
            for child in control.GetChildren():
                result = search(child, depth + 1)
                if result:
                    return result
        except Exception:
            pass
        return None
    return search(window)

def find_idle_panel():
    """Find the idle panel (has Send button, no Cancel)"""
    windows = get_vscode_windows()
    for win in windows:
        send_btn = has_button(win, "Send")
        cancel_btn = has_button(win, "Cancel")
        if send_btn and not cancel_btn:
            return win, send_btn
    return None, None

def read_text_via_clipboard(window):
    """Focus window and read input text via clipboard"""
    import pyperclip
    
    # Save current clipboard
    try:
        original_clipboard = pyperclip.paste()
    except Exception:
        original_clipboard = ""
    
    # Set a marker so we know if copy worked
    marker = "__CLIPBOARD_MARKER_12345__"
    pyperclip.copy(marker)
    
    # Focus the window
    window.SetFocus()
    time.sleep(0.3)
    
    # Use Ctrl+L to focus the chat input
    auto.SendKeys("{Ctrl}l")
    time.sleep(0.3)
    
    # Select all and copy
    auto.SendKeys("{Ctrl}a")
    time.sleep(0.1)
    auto.SendKeys("{Ctrl}c")
    time.sleep(0.2)
    
    # Read clipboard
    try:
        new_clipboard = pyperclip.paste()
    except Exception:
        new_clipboard = marker
    
    # Restore original clipboard
    try:
        pyperclip.copy(original_clipboard)
    except Exception:
        pass
    
    # Check if we got new content
    if new_clipboard != marker:
        return new_clipboard
    return "(Could not read - clipboard unchanged)"

print("=" * 70)
print("FOCUS AND READ IDLE PANEL INPUT")
print("=" * 70)

# Find the idle panel
window, send_btn = find_idle_panel()

if not window:
    print("\n❌ Could not find an IDLE panel (no window with Send button found)")
else:
    title = window.Name[:60] + "..." if len(window.Name) > 60 else window.Name
    print(f"\n✓ Found IDLE panel: {title}")
    print(f"  Send button at: {send_btn.BoundingRectangle}")
    
    print("\n--- Reading input text via clipboard method ---")
    text = read_text_via_clipboard(window)
    
    print(f"\nInput text content:")
    print("-" * 50)
    if text:
        print(text[:500] if len(text) > 500 else text)
    else:
        print("(empty)")
    print("-" * 50)

print("\nDone")
