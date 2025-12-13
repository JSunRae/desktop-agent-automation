"""Deep debug script to find Allow buttons at any depth with detailed output"""
import uiautomation as auto

# Control type IDs
CONTROLTYPE_BUTTON = 50000  # UIA_ButtonControlTypeId

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

def deep_search_buttons(vs_win, max_depth=80):
    """Deep search for buttons with extensive logging"""
    all_buttons = []
    allow_related = []
    
    def search(control, depth=0, path=""):
        if depth > max_depth:
            return
        
        try:
            control_type = control.ControlType
            name = control.Name or ""
            class_name = control.ClassName or ""
            
            # Track path for debugging
            current_path = f"{path}/{control_type}"
            
            # Check if it's a button
            if control_type == CONTROLTYPE_BUTTON:
                rect = control.BoundingRectangle
                all_buttons.append({
                    'name': name,
                    'class': class_name,
                    'rect': (rect.left, rect.top, rect.right, rect.bottom),
                    'depth': depth,
                    'path': current_path,
                    'control': control
                })
            
            # Track any Allow-related control
            if "Allow" in name and "Ctrl" in name:
                rect = control.BoundingRectangle
                allow_related.append({
                    'name': name,
                    'control_type': control_type,
                    'class': class_name,
                    'rect': (rect.left, rect.top, rect.right, rect.bottom),
                    'depth': depth,
                    'path': current_path,
                    'is_button': control_type == CONTROLTYPE_BUTTON,
                    'control': control
                })
            
            # Recurse
            for child in control.GetChildren():
                search(child, depth + 1, current_path)
                
        except Exception:
            pass
    
    search(vs_win)
    return all_buttons, allow_related

print("Finding VS Code windows on current desktop...")
print("="*80)
windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:75]
    print(f"[{i}/{len(windows)}] {title}")
    print("-"*80)
    
    buttons, allow_controls = deep_search_buttons(win)
    
    # Filter to relevant buttons
    relevant_buttons = [b for b in buttons if "Allow" in b['name'] or "Keep" in b['name']]
    
    print(f"  Total buttons found: {len(buttons)}")
    print(f"  Relevant buttons (Allow/Keep): {len(relevant_buttons)}")
    print(f"  Allow-related controls (any type): {len(allow_controls)}")
    
    if relevant_buttons:
        print("\n  [OK] RELEVANT BUTTONS:")
        for b in relevant_buttons:
            print(f"    Name: '{b['name']}'")
            print(f"    ClassName: '{b['class']}', Depth: {b['depth']}")
            print(f"    Rect: {b['rect']}")
            print()
    
    if allow_controls:
        print("\n  [INFO] ALL 'Allow (Ctrl...)' CONTROLS:")
        for a in allow_controls:
            is_btn = "[BUTTON]" if a['is_button'] else "[NOT button]"
            print(f"    {is_btn} Name: '{a['name'][:60]}...' " if len(a['name']) > 60 else f"    {is_btn} Name: '{a['name']}'")
            print(f"      Type: {a['control_type']}, Class: '{a['class']}', Depth: {a['depth']}")
            print(f"      Rect: {a['rect']}")
            print()
    
    print()

print("="*80)
print("Done.")
