"""
Deep search for panel content - looking for NEW TEXT without clicking
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

def find_all_text_recursive(control, depth=0, max_depth=25, texts=None):
    """Recursively find all text content"""
    if texts is None:
        texts = []
    if depth > max_depth:
        return texts
    
    try:
        # Check control name
        name = control.Name
        if name and len(name) > 2:
            ctrl_type = control.ControlTypeName
            texts.append((depth, ctrl_type, name[:200]))
        
        # Check value pattern
        try:
            vp = control.GetValuePattern()
            if vp and vp.Value:
                texts.append((depth, "VALUE", vp.Value[:200]))
        except Exception:
            pass
        
        # Recurse into children
        for child in control.GetChildren():
            find_all_text_recursive(child, depth + 1, max_depth, texts)
            
    except Exception:
        pass
    
    return texts

def check_for_buttons(control, depth=0, max_depth=20, buttons=None):
    """Find all buttons"""
    if buttons is None:
        buttons = []
    if depth > max_depth:
        return buttons
    
    try:
        if control.ControlTypeName == "ButtonControl":
            name = control.Name
            rect = control.BoundingRectangle
            if name:
                buttons.append(f"{name} @ ({rect.left},{rect.top},{rect.width}x{rect.height})")
        
        for child in control.GetChildren():
            check_for_buttons(child, depth + 1, max_depth, buttons)
    except Exception:
        pass
    
    return buttons

print("=" * 70)
print("DEEP PANEL OBSERVATION - Looking for NEW TEXT")
print("=" * 70)

windows = get_vscode_windows()
print(f"\nFound {len(windows)} VS Code windows\n")

for i, win in enumerate(windows):
    title = win.Name[:70] + "..." if len(win.Name) > 70 else win.Name
    print(f"\n{'='*70}")
    print(f"Window {i+1}: {title}")
    print("=" * 70)
    
    # Find buttons
    print("\n--- BUTTONS ---")
    buttons = check_for_buttons(win)
    for btn in buttons[:20]:  # Limit output
        print(f"  {btn}")
    if len(buttons) > 20:
        print(f"  ... and {len(buttons) - 20} more buttons")
    
    # Look for text containing "NEW"
    print("\n--- SEARCHING FOR 'NEW' IN TEXT ---")
    all_texts = find_all_text_recursive(win)
    new_texts = [(d, t, txt) for d, t, txt in all_texts if "NEW" in txt.upper() or "TEXT" in txt.upper()]
    
    if new_texts:
        for depth, ctrl_type, text in new_texts[:15]:
            print(f"  [depth={depth}][{ctrl_type}] {text[:100]}")
    else:
        print("  (No text containing 'NEW' or 'TEXT' found)")
    
    # Show last few text items (likely most recent chat content)
    print("\n--- LAST 10 TEXT ITEMS FOUND ---")
    for depth, ctrl_type, text in all_texts[-10:]:
        # Skip common UI elements
        if ctrl_type not in ["PaneControl", "TabItemControl"] and len(text) > 5:
            preview = text[:80] + "..." if len(text) > 80 else text
            print(f"  [{ctrl_type}] {preview}")

print("\n" + "=" * 70)
print("Done - read only, no clicks")
print("=" * 70)
