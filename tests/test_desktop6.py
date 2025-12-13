"""Test - find and click buttons on Desktop 6 (TF desktop)"""
import uiautomation as auto
import keyboard
import time
import ctypes

# Button names we're looking for
ALLOW_NAMES = ['Allow (Ctrl+Enter)', 'Allow']
KEEP_NAMES = ['Keep All Edits (Ctrl+Enter)', 'Keep', 'Keep this Change (Ctrl+Y)', 'Keep Chat Edits in this File (Ctrl+Shift+Y)']
TRY_AGAIN_NAMES = ['Try Again', 'Try Again (Ctrl+Enter)', 'Retry']
ALL_NAMES = ALLOW_NAMES + KEEP_NAMES + TRY_AGAIN_NAMES

# Additional action buttons to look for
ACTION_PATTERNS = ['Allow', 'Keep', 'Accept', 'Confirm', 'Yes', 'Retry', 'Try Again', 'Continue']

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
    try:
        for w in auto.GetRootControl().GetChildren():
            try:
                name = w.Name or ""
                if name.endswith(" - Visual Studio Code"):
                    windows.append(w)
            except:
                pass
    except:
        pass
    return windows

def find_action_buttons(win, max_depth=70):
    found = []
    def search(ctrl, depth=0):
        if depth > max_depth:
            return
        try:
            ct = ctrl.ControlType
            if ct in [50000, 50031]:  # Button, SplitButton
                name = ctrl.Name or ''
                # Check if it's an action button by name or pattern
                if name in ALL_NAMES or name.startswith('Try Again') or any(p in name for p in ACTION_PATTERNS):
                    rect = ctrl.BoundingRectangle
                    if rect.right > rect.left and rect.bottom > rect.top:
                        found.append((name, ctrl, rect))
            for child in ctrl.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    search(win)
    return found

def click_button(btn):
    try:
        rect = btn.BoundingRectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        orig = get_cursor_pos()
        set_cursor_pos(cx, cy)
        time.sleep(0.03)
        btn.Click(simulateMove=False)
        time.sleep(0.15)
        set_cursor_pos(orig[0], orig[1])
        return True
    except Exception as e:
        print(f"    Click error: {e}")
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
    time.sleep(0.3)
    # Go to target
    for _ in range(n - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.15)
    time.sleep(1.5)

print("=" * 60)
print("SWITCHING TO DESKTOP 6 (TF DESKTOP)")
print("=" * 60)

switch_to_desktop(6)

# Wait and retry to find windows
windows = []
for attempt in range(3):
    windows = find_vscode_windows()
    if windows:
        break
    print(f"  Attempt {attempt+1}: waiting...")
    time.sleep(1)

print(f"\nFound {len(windows)} VS Code window(s)")

total_clicked = 0

for win in windows:
    title = (win.Name or "Unknown")[:55]
    buttons = find_action_buttons(win)
    
    if buttons:
        print(f"\n★ {title}")
        for name, btn, rect in buttons:
            print(f"  → '{name}' at ({rect.left},{rect.top}) ... ", end="")
            if click_button(btn):
                print("CLICKED ✓")
                total_clicked += 1
            else:
                print("failed")

print("\n" + "=" * 60)
print(f"TOTAL CLICKED: {total_clicked}")
print("=" * 60)

if total_clicked >= 5:
    print("\n✓✓✓ SUCCESS! All buttons clicked! ✓✓✓")
elif total_clicked > 0:
    print(f"\n✓ Clicked {total_clicked} button(s)")
else:
    print("\n✗ No action buttons found on desktop 6")
    print("  Dumping ALL buttons and dialogs...")
    
    # Deeper inspection - look for any buttons with interesting names
    for win in windows:
        title = (win.Name or "?")[:50]
        print(f"\n  Window: {title}")
        
        all_buttons = []
        all_names_seen = set()
        
        def collect_all_buttons(c, d=0, path=""):
            if d > 50: return
            try:
                name = c.Name or ''
                ct = c.ControlType
                
                # Show ANY button
                if ct in [50000, 50031]:
                    if name and name not in all_names_seen:
                        all_names_seen.add(name)
                        all_buttons.append((name, d, ct))
                
                # Also look for potential Allow text anywhere
                if name and ('llow' in name or 'eep' in name or 'ccept' in name):
                    print(f"    !!! FOUND TEXT: '{name}' type={ct} depth={d}")
                
                for ch in c.GetChildren():
                    collect_all_buttons(ch, d+1, path + "/" + name[:10])
            except Exception as e:
                pass
        
        collect_all_buttons(win)
        
        print(f"    All unique buttons ({len(all_buttons)}):")
        for name, d, ct in sorted(all_buttons, key=lambda x: x[1]):
            if ct == 50031:
                print(f"      [SplitBtn] '{name}' (depth={d})")
            else:
                print(f"      '{name}' (depth={d})")

print("\nReturning to desktop 1...")
switch_to_desktop(1)
