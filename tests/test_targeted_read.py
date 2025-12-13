"""
Targeted search for specific text in both panels
Looking for:
- IDLE panel: "exit code 0" or "Ctrl+C" in last output  
- RUNNING panel: "NEW TEXT" in input
"""
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

def get_vscode_windows():
    """Get all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name
            if name and name.endswith(VSCODE_TITLE_SUFFIX):
                windows.append(win)
        except Exception:
            pass
    return windows

def find_all_text_deep(control, depth=0, max_depth=30, results=None, search_terms=None):
    """Find all text containing search terms"""
    if results is None:
        results = []
    if search_terms is None:
        search_terms = []
    if depth > max_depth:
        return results
    
    try:
        name = control.Name
        if name and len(name) > 3:
            # Check if any search term is in the name
            name_upper = name.upper()
            for term in search_terms:
                if term.upper() in name_upper:
                    ctrl_type = control.ControlTypeName
                    results.append((depth, ctrl_type, term, name[:300]))
                    break
        
        # Also check value pattern
        try:
            vp = control.GetValuePattern()
            if vp and vp.Value:
                val = vp.Value
                val_upper = val.upper()
                for term in search_terms:
                    if term.upper() in val_upper:
                        results.append((depth, "VALUE", term, val[:300]))
                        break
        except Exception:
            pass
        
        for child in control.GetChildren():
            find_all_text_deep(child, depth + 1, max_depth, results, search_terms)
            
    except Exception:
        pass
    
    return results

def check_buttons(window):
    """Check for key buttons"""
    buttons = {}
    button_names = ["Cancel", "Send", "Allow", "Keep Edits"]
    
    def search_buttons(control, depth=0, max_depth=20):
        if depth > max_depth:
            return
        try:
            if control.ControlTypeName == "ButtonControl":
                name = control.Name
                for btn_name in button_names:
                    if btn_name in name:
                        rect = control.BoundingRectangle
                        if rect.width() > 0 and rect.height() > 0:
                            buttons[btn_name] = f"({rect.left},{rect.top}) {rect.width()}x{rect.height()}"
            for child in control.GetChildren():
                search_buttons(child, depth + 1, max_depth)
        except Exception:
            pass
    
    search_buttons(window)
    return buttons

def get_list_items(window):
    """Get ListItem controls which often contain chat messages"""
    items = []
    
    def search_items(control, depth=0, max_depth=25):
        if depth > max_depth:
            return
        try:
            if control.ControlTypeName == "ListItemControl":
                name = control.Name
                if name and len(name) > 20:
                    items.append((depth, name[:200]))
            for child in control.GetChildren():
                search_items(child, depth + 1, max_depth)
        except Exception:
            pass
    
    search_items(window)
    return items

print("=" * 70)
print("TARGETED SEARCH FOR SPECIFIC CONTENT")
print("=" * 70)

# Search terms we're looking for
search_terms = ["exit code", "Ctrl+C", "Ctrl-C", "interrupted", "NEW TEXT", "AGAIN", "cleanly"]

windows = get_vscode_windows()
print(f"\nFound {len(windows)} VS Code windows")
print(f"Searching for: {search_terms}")

for i, win in enumerate(windows):
    title = win.Name[:60] + "..." if len(win.Name) > 60 else win.Name
    print(f"\n{'='*70}")
    print(f"Window {i+1}: {title}")
    print("=" * 70)
    
    # Check buttons to identify panel state
    buttons = check_buttons(win)
    print(f"\nKey buttons found: {buttons}")
    
    if "Cancel" in buttons:
        print("  → This is a RUNNING panel")
    elif "Send" in buttons:
        print("  → This is an IDLE/FINISHED panel")
    
    # Search for specific terms
    print(f"\n--- SEARCH RESULTS ---")
    results = find_all_text_deep(win, search_terms=search_terms)
    
    if results:
        for depth, ctrl_type, term, text in results:
            print(f"  [{term}] [{ctrl_type}] {text[:100]}...")
    else:
        print("  (No matching terms found)")
    
    # Get list items (chat messages)
    print(f"\n--- LAST 5 CHAT MESSAGES (ListItems) ---")
    items = get_list_items(win)
    for depth, text in items[-5:]:
        print(f"  {text[:100]}...")

print("\n" + "=" * 70)
print("Done")
print("=" * 70)
