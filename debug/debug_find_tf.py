"""Debug: Find the TF desktop with Allow buttons"""
import uiautomation as auto
import keyboard
import time

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

def find_all_buttons_deep(vs_win, max_depth=80):
    """Find ALL buttons with max search depth"""
    buttons = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            name = control.Name or ""
            control_type = control.ControlType
            
            # Look for ANY button
            if control_type == 50000:  # Button
                rect = control.BoundingRectangle
                if rect.right > rect.left and rect.bottom > rect.top:
                    buttons.append({
                        'name': name,
                        'rect': rect,
                        'control': control
                    })
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return buttons

print("="*80)
print("SEARCHING ALL DESKTOPS FOR TF WINDOWS WITH ALLOW BUTTONS")
print("="*80)

for desktop_num in range(1, 6):
    print(f"\n{'='*80}")
    print(f"DESKTOP {desktop_num}")
    print("="*80)
    
    switch_to_desktop(desktop_num)
    
    windows = find_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s)")
    
    tf_windows = []
    for win in windows:
        title = (win.Name or "").lower()
        if 'tf' in title or 'trading' in title or 'wsl' in title:
            tf_windows.append(win)
    
    if tf_windows:
        print(f"  Found {len(tf_windows)} TF/Trading/WSL window(s):")
        for win in tf_windows:
            title = (win.Name or "Unknown")[:70]
            print(f"    - {title}...")
            
            # Find all buttons in this window
            buttons = find_all_buttons_deep(win)
            
            # Look for action buttons
            action_buttons = [b for b in buttons if 
                             'allow' in b['name'].lower() or 
                             'keep' in b['name'].lower() or
                             'skip' in b['name'].lower() or
                             'ctrl+enter' in b['name'].lower() or
                             'ctrl+y' in b['name'].lower()]
            
            if action_buttons:
                print(f"      ★ FOUND {len(action_buttons)} ACTION BUTTON(S):")
                for btn in action_buttons:
                    print(f"        - '{btn['name']}'")
            else:
                print(f"      (No Allow/Keep buttons among {len(buttons)} buttons)")
    else:
        # Check all windows for any that might have action buttons
        for win in windows[:3]:
            title = (win.Name or "Unknown")[:50]
            buttons = find_all_buttons_deep(win)
            action_buttons = [b for b in buttons if 
                             'allow' in b['name'].lower() or 
                             'keep' in b['name'].lower()]
            if action_buttons:
                print(f"  ★ Found action buttons in: {title}")
                for btn in action_buttons:
                    print(f"    - '{btn['name']}'")

print("\n" + "="*80)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("SCAN COMPLETE")
