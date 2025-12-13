"""Robust test - find and click buttons across all desktops with proper error handling"""
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

def find_vscode_windows_safe():
    """Find VS Code windows with error handling"""
    windows = []
    try:
        for w in auto.GetRootControl().GetChildren():
            try:
                name = w.Name or ""
                if name.endswith(" - Visual Studio Code"):
                    windows.append(w)
            except Exception:
                pass
    except Exception as e:
        print(f"  (UI enumeration error: {e})")
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
                    try:
                        if ctrl.Exists(0.1):
                            rect = ctrl.BoundingRectangle
                            if rect.right > rect.left and rect.bottom > rect.top:
                                found.append((name, ctrl, rect))
                    except Exception:
                        pass
            for child in ctrl.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    try:
        search(win)
    except Exception:
        pass
    return found

def click_button(btn, name):
    """Click a button and return True if successful"""
    try:
        rect = btn.BoundingRectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        
        orig_pos = get_cursor_pos()
        set_cursor_pos(cx, cy)
        time.sleep(0.05)
        btn.Click(simulateMove=False)
        time.sleep(0.3)
        set_cursor_pos(orig_pos[0], orig_pos[1])
        
        time.sleep(0.1)
        try:
            if not btn.Exists(0.3):
                return True
        except Exception:
            return True  # If we can't check, assume it worked
        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False

def switch_to_desktop(n):
    """Switch to desktop n (1-based) with proper waits"""
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.1)
    
    # Go to desktop 1
    for _ in range(8):
        keyboard.send('win+ctrl+left')
        time.sleep(0.2)
    time.sleep(0.5)
    
    # Go to target
    for _ in range(n - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.2)
    
    # Wait for UI to stabilize
    time.sleep(1.5)

def scan_desktop(desktop_num):
    """Scan a desktop and click all found buttons"""
    clicked = 0
    
    # Try multiple times to get windows (UI may need time to refresh)
    windows = []
    for attempt in range(3):
        windows = find_vscode_windows_safe()
        if windows:
            break
        time.sleep(1)
    
    if not windows:
        print(f"  No VS Code windows found")
        return 0
    
    print(f"  {len(windows)} VS Code window(s)")
    
    for win in windows:
        try:
            title = (win.Name or "Unknown")[:50]
            buttons = find_action_buttons(win)
            
            if buttons:
                print(f"  ★ {title}")
                for name, btn, rect in buttons:
                    print(f"      '{name}' -> ", end="")
                    if click_button(btn, name):
                        print("CLICKED ✓")
                        clicked += 1
                    else:
                        print("failed")
        except Exception as e:
            print(f"  Error processing window: {e}")
    
    return clicked

def main():
    print("=" * 60)
    print("SCANNING ALL DESKTOPS FOR ACTION BUTTONS")
    print("=" * 60)
    
    total_clicked = 0
    
    for desktop in range(1, 5):
        print(f"\n--- Desktop {desktop} ---")
        switch_to_desktop(desktop)
        clicked = scan_desktop(desktop)
        total_clicked += clicked
    
    print("\n" + "=" * 60)
    print(f"TOTAL BUTTONS CLICKED: {total_clicked}")
    print("=" * 60)
    
    # Return to desktop 1
    print("\nReturning to desktop 1...")
    switch_to_desktop(1)
    
    return total_clicked

if __name__ == "__main__":
    clicked = main()
    if clicked >= 5:
        print(f"\n✓✓✓ SUCCESS! Clicked {clicked} buttons! ✓✓✓")
    elif clicked > 0:
        print(f"\n✓ Clicked {clicked} button(s)")
    else:
        print("\n✗ No buttons found")
