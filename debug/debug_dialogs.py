"""Debug: Search for Allow buttons inside Chat Confirmation Dialog groups"""
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

def find_chat_confirmation_dialogs(vs_win, max_depth=60):
    """Find all Chat Confirmation Dialog groups and their children"""
    dialogs = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            name = control.Name or ""
            
            # Look for Chat Confirmation Dialog groups
            if "Chat Confirmation Dialog" in name or "Chat confirmation required" in name:
                dialogs.append({
                    'name': name[:100],
                    'control': control,
                    'depth': depth,
                    'type': control.ControlType
                })
            
            for child in control.GetChildren():
                search(child, depth + 1)
                
        except Exception:
            pass
    
    search(vs_win)
    return dialogs

def analyze_dialog_children(dialog_control, max_depth=20):
    """Analyze all children of a dialog to find buttons"""
    buttons = []
    all_children = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            name = control.Name or ""
            ct = control.ControlType
            
            all_children.append({
                'name': name[:60] if name else "(empty)",
                'type': ct,
                'depth': depth
            })
            
            if ct == 50000:  # Button
                rect = control.BoundingRectangle
                buttons.append({
                    'name': name,
                    'rect': (rect.left, rect.top, rect.right, rect.bottom),
                    'depth': depth,
                    'control': control
                })
            
            for child in control.GetChildren():
                search(child, depth + 1)
                
        except Exception:
            pass
    
    search(dialog_control)
    return buttons, all_children

print("="*80)
print("Searching for Chat Confirmation Dialogs and their buttons")
print("="*80)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:65]
    print(f"[{i}] {title}")
    print("-"*70)
    
    dialogs = find_chat_confirmation_dialogs(win)
    print(f"  Found {len(dialogs)} Chat Confirmation Dialog(s)")
    
    for j, dialog in enumerate(dialogs, 1):
        print(f"\n  Dialog {j}: '{dialog['name'][:70]}...'")
        print(f"    Type: {dialog['type']}, Depth: {dialog['depth']}")
        
        buttons, children = analyze_dialog_children(dialog['control'])
        print(f"    Total children: {len(children)}")
        print(f"    Buttons found: {len(buttons)}")
        
        if buttons:
            print("    [BUTTONS]:")
            for btn in buttons:
                print(f"      - '{btn['name']}' at depth {btn['depth']}")
                print(f"        Rect: {btn['rect']}")
        else:
            print("    [NO BUTTONS FOUND]")
            print("    Children types:")
            type_counts = {}
            for c in children:
                t = c['type']
                type_counts[t] = type_counts.get(t, 0) + 1
            for t, count in sorted(type_counts.items()):
                type_name = {
                    50000: "Button",
                    50007: "Group",
                    50020: "Text",
                    50004: "Edit",
                    50025: "Pane",
                    50033: "List",
                }.get(t, f"Type_{t}")
                print(f"      {type_name}: {count}")
    
    print()

print("="*80)
