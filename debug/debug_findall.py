"""Debug script using FindAll to search for buttons directly"""
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

def search_with_findall(vs_win):
    """Use FindAll to search for button controls directly"""
    results = []
    
    try:
        # Search for all ButtonControl descendants
        buttons = vs_win.GetChildren()
        
        # Try a different approach - use FindAll with conditions
        all_buttons = []
        
        # Method 1: Search using Control pattern matching
        condition = auto.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.ButtonControl)
        try:
            found = vs_win.FindAll(auto.TreeScope.Descendants, condition)
            if found:
                all_buttons.extend(found)
        except Exception as e:
            print(f"  FindAll failed: {e}")
        
        for btn in all_buttons:
            try:
                name = btn.Name or ""
                if "Allow" in name or "Keep" in name:
                    rect = btn.BoundingRectangle
                    results.append({
                        'name': name,
                        'rect': (rect.left, rect.top, rect.right, rect.bottom),
                        'control': btn
                    })
            except Exception:
                pass
                
    except Exception as e:
        print(f"  Error in FindAll search: {e}")
    
    return results

def search_by_name_pattern(vs_win, max_depth=70):
    """Search for controls by name pattern with increased depth"""
    found = []
    visited = set()
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        
        # Prevent infinite loops
        try:
            ctrl_id = id(control)
            if ctrl_id in visited:
                return
            visited.add(ctrl_id)
        except Exception:
            pass
        
        try:
            name = control.Name or ""
            control_type = control.ControlType
            
            # Look for Allow button specifically
            if name == "Allow (Ctrl+Enter)" and control_type == 50000:  # ButtonControl
                rect = control.BoundingRectangle
                found.append({
                    'name': name,
                    'type': control_type,
                    'rect': (rect.left, rect.top, rect.right, rect.bottom),
                    'depth': depth,
                    'control': control
                })
            
            # Recurse into children
            for child in control.GetChildren():
                search(child, depth + 1)
                
        except Exception:
            pass
    
    search(vs_win)
    return found

def search_via_raw_element(vs_win):
    """Try using raw element walker for deeper traversal"""
    found = []
    
    try:
        # Use TreeWalker for more thorough traversal
        walker = auto.TreeWalker(auto.Condition.TrueCondition)
        
        def walk(element, depth=0, max_depth=80):
            if depth > max_depth:
                return
            
            try:
                name = element.Name or ""
                ct = element.ControlType
                
                if name == "Allow (Ctrl+Enter)" and ct == 50000:
                    rect = element.BoundingRectangle
                    found.append({
                        'name': name,
                        'type': ct,
                        'rect': (rect.left, rect.top, rect.right, rect.bottom),
                        'depth': depth
                    })
                
                # Get first child and traverse
                child = walker.GetFirstChildElement(element)
                while child:
                    walk(child, depth + 1, max_depth)
                    child = walker.GetNextSiblingElement(child)
                    
            except Exception:
                pass
        
        walk(vs_win)
        
    except Exception as e:
        print(f"  TreeWalker approach failed: {e}")
    
    return found

print("="*80)
print("Debugging Allow button search methods")
print("="*80)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:70]
    print(f"[{i}] {title}")
    print("-"*80)
    
    # Method 1: Deep recursive search
    print("  Method 1: Deep recursive search (max_depth=70)...")
    found1 = search_by_name_pattern(win, max_depth=70)
    print(f"    Found {len(found1)} 'Allow (Ctrl+Enter)' buttons")
    for f in found1:
        print(f"      Name: '{f['name']}', Rect: {f['rect']}, Depth: {f['depth']}")
    
    # Method 2: FindAll
    print("\n  Method 2: FindAll with condition...")
    found2 = search_with_findall(win)
    print(f"    Found {len(found2)} Allow/Keep buttons")
    for f in found2:
        print(f"      Name: '{f['name']}', Rect: {f['rect']}")
    
    print()

print("="*80)
print("Done.")
