"""Quick test - find and click buttons on CURRENT desktop only"""
import uiautomation as auto
import time
import ctypes

# Button names we're looking for
ALLOW_NAMES = ['Allow (Ctrl+Enter)', 'Allow']
KEEP_NAMES = ['Keep All Edits (Ctrl+Enter)', 'Keep', 'Keep this Change (Ctrl+Y)', 'Keep Chat Edits in this File (Ctrl+Shift+Y)']
ALL_NAMES = ALLOW_NAMES + KEEP_NAMES

def set_cursor_pos(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def get_cursor_pos():
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)

def find_vscode_windows():
    windows = []
    for w in auto.GetRootControl().GetChildren():
        try:
            name = w.Name or ""
            if name.endswith(" - Visual Studio Code"):
                windows.append(w)
        except Exception:
            pass
    return windows

def find_action_buttons(win, max_depth=70):
    found = []
    def search(ctrl, depth=0):
        if depth > max_depth:
            return
        try:
            if ctrl.ControlType in [50000, 50031]:  # Button, SplitButton
                name = ctrl.Name or ''
                if name in ALL_NAMES or name.startswith('Try Again'):
                    if ctrl.Exists(0.1):
                        rect = ctrl.BoundingRectangle
                        if rect.right > rect.left and rect.bottom > rect.top:
                            found.append((name, ctrl, rect))
            for child in ctrl.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    search(win)
    return found

def click_button(btn, name):
    """Click a button and return True if successful"""
    try:
        rect = btn.BoundingRectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        
        # Save cursor position
        orig_pos = get_cursor_pos()
        
        # Move to button and click
        set_cursor_pos(cx, cy)
        time.sleep(0.05)
        btn.Click(simulateMove=False)
        time.sleep(0.3)
        
        # Restore cursor
        set_cursor_pos(orig_pos[0], orig_pos[1])
        
        # Verify button is gone
        time.sleep(0.1)
        if not btn.Exists(0.3):
            return True
        return False
    except Exception as e:
        print(f"    Error clicking: {e}")
        return False

def main():
    print("=" * 60)
    print("CHECKING CURRENT DESKTOP FOR ACTION BUTTONS")
    print("=" * 60)
    
    windows = find_vscode_windows()
    print(f"\nFound {len(windows)} VS Code window(s)")
    
    total_clicked = 0
    
    for win in windows:
        title = (win.Name or "Unknown")[:60]
        print(f"\nWindow: {title}")
        
        buttons = find_action_buttons(win)
        print(f"  Found {len(buttons)} action button(s)")
        
        for name, btn, rect in buttons:
            print(f"  → '{name}' at ({rect.left}, {rect.top})")
            print("    Clicking...", end=" ")
            if click_button(btn, name):
                print("✓ SUCCESS")
                total_clicked += 1
            else:
                print("✗ FAILED")
    
    print("\n" + "=" * 60)
    print(f"TOTAL CLICKED: {total_clicked}")
    print("=" * 60)
    
    return total_clicked

if __name__ == "__main__":
    main()
