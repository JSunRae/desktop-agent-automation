"""Click ALL action buttons across all desktops"""
import uiautomation as auto
import keyboard
import time
import ctypes
import winsound

def set_cursor_pos(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def get_cursor_pos():
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)

# Button patterns
ACTION_PATTERNS = ['Allow', 'Keep', 'Retry', 'Accept', 'Confirm', 'Continue', 'Try Again']
SKIP_BUTTONS = ['Minimize', 'Maximize', 'Restore', 'Close']

def find_vscode_windows():
    windows = []
    try:
        for w in auto.GetRootControl().GetChildren():
            try:
                name = w.Name or ""
                if name.endswith(" - Visual Studio Code"):
                    windows.append(w)
            except Exception:
                pass
    except Exception:
        pass
    return windows

def find_action_buttons(win, max_depth=60):
    """Find all action buttons in a window"""
    found = []
    
    def search(ctrl, depth=0):
        if depth > max_depth:
            return
        try:
            ct = ctrl.ControlType
            name = ctrl.Name or ''
            
            if ct in [50000, 50031] and name:  # Button or SplitButton
                if any(p in name for p in ACTION_PATTERNS):
                    if name not in SKIP_BUTTONS:
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
    """Click a button and return success"""
    try:
        rect = btn.BoundingRectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        orig = get_cursor_pos()
        set_cursor_pos(cx, cy)
        time.sleep(0.05)
        btn.Click(simulateMove=False)
        time.sleep(0.15)
        set_cursor_pos(orig[0], orig[1])
        return True
    except Exception as e:
        return False

def switch_to_desktop(n):
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.1)
    # Go to desktop 1
    for _ in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    time.sleep(0.5)
    # Go to target
    for _ in range(n - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.15)
    time.sleep(3.0)  # Wait for UI tree

NUM_DESKTOPS = 6
print("=" * 70)
print(f"CLICKING ALL ACTION BUTTONS ACROSS {NUM_DESKTOPS} DESKTOPS")
print("=" * 70)

total_clicked = 0

for desktop_num in range(1, NUM_DESKTOPS + 1):
    print(f"\n--- Desktop {desktop_num} ---")
    switch_to_desktop(desktop_num)
    
    # Find windows with retry
    windows = []
    for attempt in range(3):
        windows = find_vscode_windows()
        if windows:
            break
        time.sleep(1.0)
    
    if not windows:
        print("  No VS Code windows")
        continue
    
    print(f"  Found {len(windows)} VS Code windows")
    
    for win in windows:
        title = (win.Name or "Unknown")[:45]
        buttons = find_action_buttons(win)
        
        if buttons:
            for name, btn, rect in buttons:
                print(f"    {title}: '{name}'... ", end="", flush=True)
                if click_button(btn, name):
                    print("CLICKED ✓")
                    total_clicked += 1
                else:
                    print("failed")

print("\n" + "=" * 70)
print(f"TOTAL CLICKED: {total_clicked}")
print("=" * 70)

if total_clicked > 0:
    print("\n✓ Success!")
    winsound.Beep(800, 150)
    winsound.Beep(1000, 150)
else:
    print("\n✗ No buttons found")

print("\nReturning to desktop 1...")
switch_to_desktop(1)
