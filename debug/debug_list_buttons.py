"""Debug - list ALL buttons in VS Code windows"""
import uiautomation as auto
import keyboard
import time

def find_vscode_windows_safe():
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

def find_all_buttons(win, max_depth=70):
    """Find ALL buttons (not just action buttons)"""
    found = []
    def search(ctrl, depth=0):
        if depth > max_depth:
            return
        try:
            if ctrl.ControlType in [50000, 50031]:  # Button, SplitButton
                name = ctrl.Name or ''
                if name:  # Only named buttons
                    rect = ctrl.BoundingRectangle
                    if rect.right > rect.left:
                        found.append((name, rect.left, rect.top))
            for child in ctrl.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    try:
        search(win)
    except Exception:
        pass
    return found

def switch_to_desktop(n):
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.1)
    for _ in range(8):
        keyboard.send('win+ctrl+left')
        time.sleep(0.2)
    time.sleep(0.5)
    for _ in range(n - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.2)
    time.sleep(1.5)

# Keywords to look for
KEYWORDS = ['allow', 'keep', 'skip', 'try', 'accept', 'apply', 'confirm']

print("=" * 70)
print("LISTING ALL BUTTONS IN VS CODE WINDOWS")
print("=" * 70)

for desktop in range(1, 5):
    print(f"\n{'='*70}")
    print(f"DESKTOP {desktop}")
    print("=" * 70)
    
    switch_to_desktop(desktop)
    time.sleep(0.5)
    
    windows = find_vscode_windows_safe()
    if not windows:
        print("  No VS Code windows")
        continue
    
    print(f"  {len(windows)} VS Code window(s)")
    
    for i, win in enumerate(windows[:4], 1):  # Check first 4 windows
        try:
            title = (win.Name or "Unknown")[:50]
            print(f"\n  [{i}] {title}")
            
            buttons = find_all_buttons(win)
            
            # Filter to interesting buttons
            interesting = [(n, x, y) for n, x, y in buttons 
                          if any(kw in n.lower() for kw in KEYWORDS)]
            
            if interesting:
                print(f"      ★ INTERESTING BUTTONS:")
                for name, x, y in interesting:
                    print(f"          '{name}' at ({x}, {y})")
            else:
                print(f"      (No action buttons among {len(buttons)} buttons)")
                # Show a few button names for debugging
                if buttons:
                    sample = [n for n, _, _ in buttons[:5]]
                    print(f"      Sample: {sample}")
        except Exception as e:
            print(f"      Error: {e}")

print("\n" + "=" * 70)
print("Returning to desktop 1...")
switch_to_desktop(1)
