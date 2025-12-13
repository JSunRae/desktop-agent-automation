"""Debug script to find ALL buttons on all desktops - to identify button name changes"""
import uiautomation as auto
import keyboard
import time

MAX_DESKTOPS = 5

def find_vscode_windows():
    """Find all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name or ""
            if name.endswith(" - Visual Studio Code"):
                windows.append(win)
        except:
            pass
    return windows

def find_all_buttons_with_keywords(vs_win, keywords, max_depth=60):
    """Find all buttons containing any of the keywords (case-insensitive)"""
    found_buttons = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            control_type = control.ControlType
            name = control.Name or ""
            name_lower = name.lower()
            
            # Check if it's a button by ControlType
            if control_type == auto.ControlType.ButtonControl:
                # Check if ANY keyword is in the button name
                for keyword in keywords:
                    if keyword.lower() in name_lower:
                        rect = control.BoundingRectangle
                        found_buttons.append({
                            'name': name,
                            'rect': f"({rect.left},{rect.top})-({rect.right},{rect.bottom})",
                            'control': control,
                            'keyword': keyword
                        })
                        break  # Don't add same button multiple times
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception as e:
            pass
    
    search(vs_win)
    return found_buttons

def switch_to_desktop(desktop_number):
    """Switch to a specific virtual desktop"""
    # Go to desktop 1 first
    for i in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    
    time.sleep(0.3)
    
    # Navigate to target desktop
    for i in range(desktop_number - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.15)
    
    time.sleep(0.5)

# Keywords to search for in button names
KEYWORDS = [
    'allow', 'keep', 'skip', 'try again', 'retry', 'ctrl+enter', 
    'accept', 'apply', 'confirm', 'undo', 'continue'
]

print("="*80)
print("SEARCHING ALL DESKTOPS FOR ACTION BUTTONS")
print("="*80)
print(f"Keywords: {KEYWORDS}")
print()

for desktop_num in range(1, MAX_DESKTOPS + 1):
    print(f"\n{'='*80}")
    print(f"DESKTOP {desktop_num}")
    print("="*80)
    
    switch_to_desktop(desktop_num)
    time.sleep(0.5)
    
    windows = find_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s) on desktop {desktop_num}")
    
    if not windows:
        print("  (no windows)")
        continue
    
    for i, win in enumerate(windows, 1):
        title = (win.Name or "Unknown")[:60]
        print(f"\n  [{i}] Window: {title}...")
        print("  " + "-"*70)
        
        buttons = find_all_buttons_with_keywords(win, KEYWORDS)
        
        if buttons:
            print(f"  ✓ Found {len(buttons)} action button(s):")
            for btn_info in buttons:
                print(f"      - '{btn_info['name']}' (matched: {btn_info['keyword']})")
                print(f"        Rect: {btn_info['rect']}")
        else:
            print("  ✗ No action buttons found with keywords")

print("\n" + "="*80)
print("SCAN COMPLETE")
print("="*80)

# Return to desktop 1
switch_to_desktop(1)
