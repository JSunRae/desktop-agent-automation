"""Debug script to find ALL control types with Allow/Keep in name"""
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

def find_controls_by_name(vs_win, keywords, max_depth=60):
    """Find ALL controls (any type) containing keywords in their name"""
    found_controls = []
    
    # Map control type ID to name
    type_names = {
        50000: 'Button', 50001: 'Calendar', 50002: 'CheckBox', 
        50003: 'ComboBox', 50004: 'Edit', 50005: 'Hyperlink',
        50006: 'Image', 50007: 'ListItem', 50008: 'List',
        50009: 'Menu', 50010: 'MenuBar', 50011: 'MenuItem',
        50012: 'ProgressBar', 50013: 'RadioButton', 50014: 'ScrollBar',
        50015: 'Slider', 50016: 'Spinner', 50017: 'StatusBar',
        50018: 'Tab', 50019: 'TabItem', 50020: 'Text',
        50021: 'ToolBar', 50022: 'ToolTip', 50023: 'Tree',
        50024: 'TreeItem', 50025: 'Custom', 50026: 'Group',
        50027: 'Thumb', 50028: 'DataGrid', 50029: 'DataItem',
        50030: 'Document', 50031: 'SplitButton', 50032: 'Window',
        50033: 'Pane', 50034: 'Header', 50035: 'HeaderItem',
        50036: 'Table', 50037: 'TitleBar', 50038: 'Separator',
    }
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            name = control.Name or ""
            name_lower = name.lower()
            
            # Check if ANY keyword is in the name
            for keyword in keywords:
                if keyword.lower() in name_lower:
                    control_type = control.ControlType
                    type_name = type_names.get(control_type, f'Unknown({control_type})')
                    rect = control.BoundingRectangle
                    
                    found_controls.append({
                        'name': name[:100],
                        'type': type_name,
                        'type_id': control_type,
                        'rect': f"({rect.left},{rect.top})-({rect.right},{rect.bottom})",
                        'control': control,
                        'keyword': keyword
                    })
                    break
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return found_controls

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

# Keywords that might appear in action buttons
KEYWORDS = ['allow', 'keep', 'skip']

print("="*80)
print("SEARCHING FOR ACTION CONTROLS (ANY TYPE)")
print("="*80)
print(f"Keywords: {KEYWORDS}")

# Check desktops 2 and 4 (where we found windows)
for desktop_num in [2, 4]:
    print(f"\n{'='*80}")
    print(f"DESKTOP {desktop_num}")
    print("="*80)
    
    switch_to_desktop(desktop_num)
    
    windows = find_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s)")
    
    all_found = []
    for i, win in enumerate(windows, 1):
        title = (win.Name or "Unknown")[:60]
        
        controls = find_controls_by_name(win, KEYWORDS)
        
        if controls:
            print(f"\n  [{i}] {title}...")
            for ctrl_info in controls:
                print(f"      ★ [{ctrl_info['type']}] '{ctrl_info['name'][:70]}'")
                print(f"        Matched: '{ctrl_info['keyword']}', Rect: {ctrl_info['rect']}")
                all_found.append(ctrl_info)
    
    if not all_found:
        print("\n  ✗ NO CONTROLS found with 'allow', 'keep', or 'skip' in name!")
    else:
        print(f"\n  ✓ Total: {len(all_found)} controls found with keywords")
        
        # Count by type
        type_counts = {}
        for c in all_found:
            type_counts[c['type']] = type_counts.get(c['type'], 0) + 1
        print(f"  By type: {type_counts}")

print("\n" + "="*80)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("SCAN COMPLETE")
