"""Debug script to find action buttons across ALL windows on a desktop"""
import uiautomation as auto
import keyboard
import time

def find_vscode_windows():
    """Find all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name or ""
            if name.endswith(" - Visual Studio Code"):
                windows.append(win)
        except Exception:
            pass
    return windows

def find_all_buttons(vs_win, max_depth=70):
    """Find ALL buttons regardless of name"""
    buttons = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            control_type = control.ControlType
            name = control.Name or ""
            
            # Check if it's a button (type 50000) or SplitButton (50031)
            if control_type in [50000, 50031]:  # Button, SplitButton
                rect = control.BoundingRectangle
                # Only include if visible
                if rect.right > rect.left and rect.bottom > rect.top:
                    buttons.append({
                        'name': name,
                        'type': 'Button' if control_type == 50000 else 'SplitButton',
                        'rect': rect,
                        'control': control
                    })
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return buttons

def switch_to_desktop(desktop_number):
    """Switch to a specific virtual desktop"""
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.2)
    
    for i in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.3)
    time.sleep(1)
    
    for i in range(desktop_number - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.3)
    time.sleep(2)

print("="*80)
print("FINDING ALL BUTTONS ON DESKTOP 2")
print("="*80)

switch_to_desktop(2)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)")

# Look for potentially interesting buttons (short names that could be actions)
ACTION_KEYWORDS = ['allow', 'keep', 'skip', 'accept', 'apply', 'confirm', 
                   'continue', 'yes', 'no', 'ok', 'cancel', 'ctrl+enter',
                   'ctrl+y', 'try again', 'retry']

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:50]
    print(f"\n[{i}] {title}...")
    print("-"*70)
    
    buttons = find_all_buttons(win)
    
    # Filter to interesting buttons
    action_buttons = []
    for btn in buttons:
        name_lower = btn['name'].lower()
        # Check if matches any keyword
        for kw in ACTION_KEYWORDS:
            if kw in name_lower:
                action_buttons.append((btn, kw))
                break
        else:
            # Also include short-named buttons (likely action buttons)
            if len(btn['name']) <= 20 and btn['name']:
                action_buttons.append((btn, 'short-name'))
    
    if action_buttons:
        print(f"  ✓ Found {len(action_buttons)} potential action button(s):")
        for btn, reason in action_buttons:
            r = btn['rect']
            print(f"    [{btn['type']}] '{btn['name']}' ({reason})")
            print(f"      at ({r.left},{r.top})-({r.right},{r.bottom})")
    else:
        print("  No obvious action buttons found")
    
    # Show count of all buttons  
    print(f"  (Total buttons in window: {len(buttons)})")

print("\n" + "="*80)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("Done.")
