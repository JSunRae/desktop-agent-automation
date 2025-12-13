"""
Debug script to inspect the hierarchy of the Chat list and find Allow buttons.
Uses multiple walking strategies to diagnose why buttons are missed.
"""
import uiautomation as auto
import time
from automation.config import VSCODE_TITLE_SUFFIX

def find_vscode_windows():
    print("Searching for VS Code windows...")
    root = auto.GetRootControl()
    windows = []
    for win in root.GetChildren():
        if win.Name.endswith(VSCODE_TITLE_SUFFIX):
            print(f"Found VS Code: {win.Name}")
            windows.append(win)
    return windows

def walk_raw(control, indent=0, max_depth=10):
    if indent > max_depth:
        return
    
    try:
        children = control.GetChildren()
        for child in children:
            name = child.Name
            role = child.LocalizedControlType
            
            # Check for interesting elements
            is_interesting = "Chat" in name or "Allow" in name or "Confirm" in name
            
            if is_interesting:
                print(f"{'  ' * indent}[{role}] {name} (Rect: {child.BoundingRectangle})")
            
            # Recurse if it's a container or interesting
            if is_interesting or indent < 3:
                walk_raw(child, indent + 1, max_depth)
                
    except Exception as e:
        print(f"{'  ' * indent}Error: {e}")

def find_allow_button_specifically(window):
    print("\n--- Searching specifically for 'Allow' button ---")
    
    # Strategy 1: Control View (Standard)
    print("\nStrategy 1: Standard Control View Search")
    # GetFirstChild is not available on Control directly in some versions, use GetChildren()[0] or loop
    # Actually uiautomation controls usually have GetFirstChild. 
    # But let's use a safer way:
    
    found_std = None
    try:
        # Use WalkTree or custom search
        # WalkTree yields (control, depth) or (control, depth, remaining) depending on version?
        # Actually it yields (control, depth) usually.
        # But let's just use a simple recursive function to be safe
        
        def search(control, depth):
            if depth > 50: return None
            if "Allow" in control.Name and control.ControlType == auto.ControlType.ButtonControl:
                return control
            
            for child in control.GetChildren():
                res = search(child, depth + 1)
                if res: return res
            return None

        found_std = search(window, 0)
    except Exception as e:
        print(f"Error in walk: {e}")

    if found_std:
        print(f"✓ Found in Standard View: {found_std.Name} - {found_std.BoundingRectangle}")
    else:
        print("✗ Not found in Standard View")

    # Strategy 2: Raw View
    print("\nStrategy 2: Raw View Search")
    
    # Let's try a deep search using WalkScope if available, otherwise manual
    try:
        # found_deep = window.GetFirstChild(lambda c: "Allow" in c.Name, scope=auto.TreeScope.Descendants)
        # TreeScope not available in this version?
        pass
    except Exception as e:
        print(f"Error in deep search: {e}")

def inspect_chat_list(window):
    print("\n--- Inspecting 'Chat' list ---")
    try:
        chat_lists = []
        
        def find_all_chats(control, depth):
            if depth > 50: return
            # Relaxed condition: Any ListControl
            if control.ControlType == auto.ControlType.ListControl:
                print(f"Found List at depth {depth}: '{control.Name}' {control.BoundingRectangle}")
                chat_lists.append(control)
            
            for child in control.GetChildren():
                find_all_chats(child, depth + 1)
            
        find_all_chats(window, 0)
        
        for i, chat_list in enumerate(chat_lists):
            print(f"\nInspecting Chat List #{i+1}: {chat_list.BoundingRectangle}")
            # ... (rest of inspection logic)
            
            # Use RawViewWalker to inspect children
            # ...
            
            # Use GetChildren directly
            children = chat_list.GetChildren()
            print(f"Child count: {len(children)}")
            
            def print_tree(control, indent_level=0, max_depth=4):
                if indent_level > max_depth:
                    return
                
                try:
                    c_children = control.GetChildren()
                    for k, c in enumerate(c_children):
                        name = c.Name
                        role = c.LocalizedControlType
                        
                        # Always print if it looks like a button or dialog
                        is_target = "Allow" in name or "Confirm" in name or c.ControlType == auto.ControlType.ButtonControl
                        
                        # Print if target, or if we are at top level (to see structure), or if parent was interesting
                        if is_target or indent_level < 2:
                            prefix = "  " * (indent_level + 1)
                            print(f"{prefix}[{k}] {role} '{name}' ({c.ControlType})")
                        
                        # Recurse
                        print_tree(c, indent_level + 1, max_depth)
                except Exception as e:
                    print(f"Error in tree walk: {e}")

            print_tree(chat_list)

    except Exception as e:
        print(f"Error inspecting chat list: {e}")

def main():
    windows = find_vscode_windows()
    if not windows:
        print("No VS Code windows found.")
        return

    for i, win in enumerate(windows):
        print(f"\n\n=== Scanning Window {i+1}: {win.Name} ===")
        find_allow_button_specifically(win)
        inspect_chat_list(win)

if __name__ == "__main__":
    main()
