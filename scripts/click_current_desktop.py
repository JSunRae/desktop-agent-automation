"""Find and click action buttons on current desktop"""
import uiautomation as auto
import ctypes
import time

def set_cursor_pos(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def get_cursor_pos():
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)

print("=" * 60)
print("FIND AND CLICK ACTION BUTTONS ON CURRENT DESKTOP")
print("=" * 60)

# Get VS Code windows
root = auto.GetRootControl()
vscode_windows = []
for w in root.GetChildren():
    try:
        name = w.Name or ""
        if " - Visual Studio Code" in name:
            vscode_windows.append(w)
    except Exception:
        pass

print(f"Found {len(vscode_windows)} VS Code windows")

action_patterns = ['Allow', 'Keep', 'Retry', 'Accept', 'Confirm', 'Continue', 'Try Again']
skip_buttons = ['Minimize', 'Maximize', 'Restore', 'Close']

total_clicked = 0

for win in vscode_windows:
    title = (win.Name or "Unknown")[:55]
    print(f"\nWindow: {title}")
    
    found_buttons = []
    
    def search(ctrl, depth=0):
        if depth > 60:
            return
        try:
            ct = ctrl.ControlType
            name = ctrl.Name or ''
            
            if ct in [50000, 50031] and name:  # Button or SplitButton
                if any(p in name for p in action_patterns):
                    if name not in skip_buttons:
                        rect = ctrl.BoundingRectangle
                        if rect.right > rect.left and rect.bottom > rect.top:
                            found_buttons.append((name, ctrl, rect))
            
            for child in ctrl.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(win)
    
    if found_buttons:
        print(f"  Found {len(found_buttons)} action button(s):")
        for name, btn, rect in found_buttons:
            print(f"    Clicking '{name}'... ", end="", flush=True)
            
            try:
                # Save cursor position
                orig = get_cursor_pos()
                
                # Move to button center
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                set_cursor_pos(cx, cy)
                time.sleep(0.05)
                
                # Click
                btn.Click(simulateMove=False)
                time.sleep(0.2)
                
                # Restore cursor
                set_cursor_pos(orig[0], orig[1])
                
                print("CLICKED ✓")
                total_clicked += 1
            except Exception as e:
                print(f"FAILED: {e}")
    else:
        print("  No action buttons found")

print("\n" + "=" * 60)
print(f"TOTAL CLICKED: {total_clicked}")
print("=" * 60)

if total_clicked > 0:
    print("\n✓ Success!")
    # Beep to indicate success
    import winsound
    winsound.Beep(800, 150)
else:
    print("\n✗ No buttons clicked")
