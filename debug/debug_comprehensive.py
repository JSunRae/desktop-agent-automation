"""Debug script to understand why Allow buttons aren't found on desktop 6

Key insight from user's data:
- Button Name: "Allow (Ctrl+Enter)" 
- ControlType: UIA_ButtonControlTypeId (0xC350 = 50000)
- class="Chrome_RenderWidgetHostHWND"
- hwnd=0x0000000000060310

The button EXISTS but isn't being found by our recursive search.
"""
import uiautomation as auto

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

def comprehensive_button_search(vs_win, max_depth=80):
    """Search with multiple strategies"""
    buttons_found = []
    all_controls_with_allow = []
    button_type_count = 0
    max_depth_reached = 0
    
    def search(control, depth=0):
        nonlocal button_type_count, max_depth_reached
        
        if depth > max_depth:
            return
        
        if depth > max_depth_reached:
            max_depth_reached = depth
        
        try:
            name = control.Name or ""
            control_type = control.ControlType
            class_name = control.ClassName or ""
            
            # Count all buttons
            if control_type == 50000:  # ButtonControl
                button_type_count += 1
                
                # Check if it's an Allow button
                if "Allow" in name:
                    rect = control.BoundingRectangle
                    buttons_found.append({
                        'name': name,
                        'class': class_name,
                        'rect': (rect.left, rect.top, rect.right, rect.bottom),
                        'depth': depth
                    })
            
            # Also track any control with "Allow (Ctrl" in name
            if "Allow (Ctrl" in name:
                rect = control.BoundingRectangle
                all_controls_with_allow.append({
                    'name': name[:80],
                    'type': control_type,
                    'class': class_name,
                    'rect': (rect.left, rect.top, rect.right, rect.bottom),
                    'depth': depth,
                    'is_button': control_type == 50000
                })
            
            # Get children
            children = control.GetChildren()
            for child in children:
                search(child, depth + 1)
                
        except Exception as e:
            pass
    
    search(vs_win)
    
    return {
        'buttons': buttons_found,
        'allow_controls': all_controls_with_allow,
        'total_buttons': button_type_count,
        'max_depth': max_depth_reached
    }

def search_by_hwnd():
    """Try to find the specific hwnd mentioned by user"""
    target_hwnd = 0x60310  # From user's example
    try:
        ctrl = auto.ControlFromHandle(target_hwnd)
        if ctrl:
            print(f"\n  Found control by hwnd 0x{target_hwnd:X}:")
            print(f"    Name: {ctrl.Name}")
            print(f"    ControlType: {ctrl.ControlType}")
            print(f"    ClassName: {ctrl.ClassName}")
            rect = ctrl.BoundingRectangle
            print(f"    Rect: ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})")
            return ctrl
    except Exception as e:
        print(f"\n  Could not find control by hwnd: {e}")
    return None

print("="*80)
print("Comprehensive Allow Button Debug")
print("="*80)

# First try to find by HWND
print("\nTrying to find control by hwnd (from user's example)...")
search_by_hwnd()

print("\n" + "-"*80)
print("Searching VS Code windows...")

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:70]
    print(f"[{i}] {title}")
    print("-"*70)
    
    result = comprehensive_button_search(win)
    
    print(f"  Total buttons found (ControlType=50000): {result['total_buttons']}")
    print(f"  Max tree depth reached: {result['max_depth']}")
    print(f"  Allow buttons found: {len(result['buttons'])}")
    print(f"  Controls with 'Allow (Ctrl' in name: {len(result['allow_controls'])}")
    
    if result['buttons']:
        print("\n  [ALLOW BUTTONS]:")
        for b in result['buttons']:
            print(f"    - Name: '{b['name']}'")
            print(f"      Class: '{b['class']}', Depth: {b['depth']}")
            print(f"      Rect: {b['rect']}")
    
    if result['allow_controls']:
        print("\n  [ALL 'Allow (Ctrl' CONTROLS]:")
        for a in result['allow_controls']:
            btn_marker = "[BTN]" if a['is_button'] else "[---]"
            print(f"    {btn_marker} Type={a['type']}, Depth={a['depth']}")
            print(f"        Name: '{a['name']}...'")
            print(f"        Rect: {a['rect']}")
    
    print()

print("="*80)
print("\nAnalysis:")
print("If 'Allow (Ctrl+Enter)' buttons exist but aren't found:")
print("1. They may be at depth > 80 (increase max_depth)")
print("2. GetChildren() may not traverse into Chrome render widgets")
print("3. The window may not be active/visible when searched")
print("="*80)
