"""Scan ALL desktops for VS Code windows with action buttons"""
import uiautomation as auto
import keyboard
import time

# Button patterns to find
ALLOW_NAMES = ['Allow (Ctrl+Enter)', 'Allow']
KEEP_NAMES = ['Keep All Edits (Ctrl+Enter)', 'Keep', 'Keep this Change (Ctrl+Y)', 'Keep Chat Edits in this File (Ctrl+Shift+Y)']
TRY_AGAIN_NAMES = ['Try Again', 'Try Again (Ctrl+Enter)', 'Retry']
ALL_ACTION_PATTERNS = ['Allow', 'Keep', 'Accept', 'Confirm', 'Yes', 'Retry', 'Try Again', 'Continue']

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

def count_action_buttons(win, max_depth=70):
    """Count action buttons (don't click, just count)"""
    count = 0
    found_names = []
    
    def search(ctrl, depth=0):
        nonlocal count, found_names
        if depth > max_depth:
            return
        try:
            ct = ctrl.ControlType
            if ct in [50000, 50031]:  # Button, SplitButton
                name = ctrl.Name or ''
                # Check if it's an action button
                if any(p in name for p in ALL_ACTION_PATTERNS):
                    # Skip common non-action buttons
                    if name in ['Minimize', 'Maximize', 'Restore', 'Close']:
                        pass
                    else:
                        rect = ctrl.BoundingRectangle
                        if rect.right > rect.left and rect.bottom > rect.top:
                            count += 1
                            if name not in found_names:
                                found_names.append(name)
            for child in ctrl.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(win)
    return count, found_names

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
    # CRITICAL: Wait longer for UI tree to refresh (3 seconds)
    time.sleep(3.0)

print("=" * 70)
print("SCANNING ALL 6 DESKTOPS FOR ACTION BUTTONS")
print("(With improved 3-second wait after each switch)")
print("=" * 70)

results = {}

for desktop_num in range(1, 7):  # Desktops 1-6
    print(f"\n--- Desktop {desktop_num} ---")
    switch_to_desktop(desktop_num)
    
    # Multiple attempts to find windows
    windows = []
    for attempt in range(3):
        windows = find_vscode_windows()
        if windows:
            break
        print(f"  Attempt {attempt+1}: No windows, waiting...")
        time.sleep(1.0)
    
    print(f"  Found {len(windows)} VS Code window(s)")
    
    desktop_results = {'windows': [], 'total_buttons': 0}
    
    for win in windows:
        title = (win.Name or "Unknown")[:50]
        btn_count, btn_names = count_action_buttons(win)
        desktop_results['windows'].append((title, btn_count, btn_names))
        desktop_results['total_buttons'] += btn_count
        
        if btn_count > 0:
            print(f"  ★ {title}")
            print(f"    → {btn_count} action button(s): {btn_names[:5]}")
    
    results[desktop_num] = desktop_results
    
    if desktop_results['total_buttons'] > 0:
        print(f"  TOTAL: {desktop_results['total_buttons']} action buttons on this desktop")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

total_all = 0
for d in range(1, 7):
    r = results.get(d, {'total_buttons': 0, 'windows': []})
    n_windows = len(r.get('windows', []))
    total_all += r['total_buttons']
    print(f"  Desktop {d}: {n_windows} VS Code windows, {r['total_buttons']} action buttons")

if total_all == 0:
    print("\n  No action buttons found on any desktop!")
else:
    print(f"\n  GRAND TOTAL: {total_all} action buttons across all desktops")

print("\nReturning to desktop 1...")
switch_to_desktop(1)
