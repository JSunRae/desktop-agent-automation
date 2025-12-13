"""
Read text from THIS panel's input box using direct window search.
Uses clipboard method: Focus input -> Ctrl+A -> Ctrl+C
"""
import uiautomation as auto
import time
import pyperclip

# Try different methods to find VS Code windows
def find_vscode_windows_method1():
    """Method 1: Search by ClassName"""
    windows = []
    try:
        # Search for Chrome_WidgetWin_1 class (Electron/VS Code)
        win = auto.WindowControl(searchDepth=1, ClassName="Chrome_WidgetWin_1")
        if win.Exists(1, 1):
            windows.append(win)
            # Try to find more
            while True:
                next_win = win.GetNextSiblingControl()
                if not next_win or next_win.ClassName != "Chrome_WidgetWin_1":
                    break
                windows.append(next_win)
                win = next_win
    except Exception as e:
        print(f"Method 1 error: {e}")
    return windows

def find_vscode_windows_method2():
    """Method 2: Search by partial name"""
    windows = []
    try:
        # Use FindAll with Visual Studio Code in name
        all_wins = auto.GetRootControl().GetChildren()
        for w in all_wins:
            try:
                name = w.Name
                if name and "Visual Studio Code" in name:
                    windows.append(w)
            except:
                pass
    except Exception as e:
        print(f"Method 2 error: {e}")
    return windows

def find_vscode_windows_method3():
    """Method 3: Direct WindowControl search"""
    windows = []
    try:
        # Try searching for windows with specific pattern
        win = auto.WindowControl(searchDepth=1, SubName="Visual Studio Code")
        if win.Exists(0.5, 0.5):
            windows.append(win)
    except Exception as e:
        print(f"Method 3 error: {e}")
    return windows

def has_button(window, button_name, max_depth=20):
    """Check if window has a specific button"""
    def search(control, depth=0):
        if depth > max_depth:
            return None
        try:
            if control.ControlTypeName == "ButtonControl":
                ctrl_name = control.Name or ""
                if button_name in ctrl_name:
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

def read_text_via_clipboard(window):
    """Focus window and read input text via clipboard"""
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
    return ""

def main():
    print("=" * 60)
    print("Finding VS Code windows and reading panel input")
    print("=" * 60)
    
    # Try all methods
    print("\nMethod 1 (ClassName search)...")
    windows1 = find_vscode_windows_method1()
    print(f"  Found: {len(windows1)} windows")
    
    print("\nMethod 2 (GetChildren with filter)...")
    windows2 = find_vscode_windows_method2()
    print(f"  Found: {len(windows2)} windows")
    
    print("\nMethod 3 (SubName search)...")
    windows3 = find_vscode_windows_method3()
    print(f"  Found: {len(windows3)} windows")
    
    # Combine unique windows
    all_windows = []
    seen = set()
    for win in windows1 + windows2 + windows3:
        try:
            handle = win.NativeWindowHandle
            if handle not in seen:
                seen.add(handle)
                all_windows.append(win)
        except:
            pass
    
    print(f"\nTotal unique windows: {len(all_windows)}")
    
    if not all_windows:
        print("\n❌ No VS Code windows found from terminal context")
        print("   This is expected - terminal runs in isolated context")
        return
    
    # Check each window for panel state
    for i, win in enumerate(all_windows):
        try:
            name = win.Name or "(no name)"
            short_name = name[:50] + "..." if len(name) > 50 else name
            print(f"\nWindow {i+1}: {short_name}")
            
            cancel = has_button(win, "Cancel")
            send = has_button(win, "Send")
            
            if cancel:
                print("  State: RUNNING (has Cancel button)")
                print("  → Reading input text...")
                text = read_text_via_clipboard(win)
                print(f"  Content: {text[:200] if text else '(empty)'}")
            elif send:
                print("  State: IDLE (has Send button)")
            else:
                print("  State: UNKNOWN (no Cancel/Send button)")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    main()
