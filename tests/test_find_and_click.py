"""Test script to find and click Allow buttons"""
import uiautomation as auto
import keyboard
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
        time.sleep(0.2)
        
        # Restore cursor
        set_cursor_pos(orig_pos[0], orig_pos[1])
        
        # Verify button is gone
        if not btn.Exists(0.2):
            return True
        return False
    except Exception as e:
        print(f"    Error clicking: {e}")
        return False

def switch_to_desktop(n):
    """Switch to desktop n (1-based)"""
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.1)
    
    # Go to desktop 1
    for _ in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    time.sleep(0.3)
    
    # Go to target
    for _ in range(n - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.15)
    time.sleep(1)

def scan_and_click_all():
    """Scan all desktops and click all found buttons"""
    total_clicked = 0
    
    print("=" * 60)
    print("SCANNING ALL DESKTOPS FOR ACTION BUTTONS")
    print("=" * 60)
    
    for desktop in range(1, 6):
        print(f"\n--- Desktop {desktop} ---")
        switch_to_desktop(desktop)
        
        windows = find_vscode_windows()
        if not windows:
            print("  No VS Code windows")
            continue
        
        print(f"  Found {len(windows)} VS Code window(s)")
        
        for win in windows:
            title = (win.Name or "Unknown")[:50]
            buttons = find_action_buttons(win)
            
            if buttons:
                print(f"  Window: {title}")
                for name, btn, rect in buttons:
                    print(f"    → Found: '{name}' at ({rect.left}, {rect.top})")
                    print(f"      Clicking...", end=" ")
                    if click_button(btn, name):
                        print("✓ SUCCESS")
                        total_clicked += 1
                    else:
                        print("✗ FAILED (button may still be there)")
    
    print("\n" + "=" * 60)
    print(f"TOTAL BUTTONS CLICKED: {total_clicked}")
    print("=" * 60)
    
    # Return to desktop 1
    print("\nReturning to desktop 1...")
    switch_to_desktop(1)
    
    return total_clicked

if __name__ == "__main__":
    clicked = scan_and_click_all()
    if clicked > 0:
        print(f"\n✓ Successfully clicked {clicked} button(s)!")
    else:
        print("\n✗ No buttons found to click")
