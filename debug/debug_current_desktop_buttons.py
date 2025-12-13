"""Quick debug script to scan current desktop for Allow buttons"""
import time
import uiautomation as auto
from automation.config import ALLOW_BUTTON_NAMES, ALL_ACTION_BUTTON_NAMES, VSCODE_TITLE_SUFFIX

def find_vscode_windows():
    """Find all VS Code windows on current desktop."""
    windows = []
    for w in auto.GetRootControl().GetChildren():
        try:
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                name = w.Name or ""
                if name.endswith(VSCODE_TITLE_SUFFIX):
                    windows.append(w)
        except Exception:
            pass
    return windows

def find_all_buttons_deep(vs_win, max_depth=70):
    """Deep search for all buttons in window."""
    buttons = []
    scanned_count = 0
    
    def search(control, depth=0):
        nonlocal scanned_count
        if depth > max_depth:
            return
        try:
            scanned_count += 1
            ct = control.ControlType
            name = control.Name or ""
            
            # Button (50000) or SplitButton (50031)
            if ct in [50000, 50031]:
                rect = control.BoundingRectangle
                buttons.append({
                    'name': name,
                    'type': 'Button' if ct == 50000 else 'SplitButton',
                    'rect': rect,
                    'control': control,
                    'depth': depth
                })
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception as e:
            # print(f"Error at depth {depth}: {e}")
            pass
    
    search(vs_win)
    return buttons, scanned_count

def main():
    print("=" * 70)
    print("BUTTON SCANNER - Checking Current Desktop")
    print("=" * 70)
    print()
    
    windows = find_vscode_windows()
    print(f"  Found {len(windows)} VS Code window(s)")
    
    for i, win in enumerate(windows, 1):
        title = (win.Name or "Unknown")[:60]
        print(f"\n  [{i}] {title}")
        
        buttons, scanned = find_all_buttons_deep(win)
        print(f"      Scanned controls: {scanned}")
        
        # Filter to action buttons we care about
        action_buttons = []
        for btn in buttons:
            name = btn['name']
            # Check against configured names
            if name in ALLOW_BUTTON_NAMES or name in ALL_ACTION_BUTTON_NAMES:
                action_buttons.append(btn)
            # Also check for partial matches
            elif 'Allow' in name or 'Keep' in name or 'Try Again' in name:
                action_buttons.append(btn)
        
        if action_buttons:
            print(f"      ✓ Found {len(action_buttons)} ACTION BUTTON(S):")
            for btn in action_buttons:
                r = btn['rect']
                print(f"        - [{btn['type']}] \"{btn['name']}\"")
                print(f"          bounds: ({r.left},{r.top})-({r.right},{r.bottom}), depth={btn['depth']}")
        else:
            print("      ✗ No action buttons found")
        
        # Show total button count for debugging
        print(f"      (Total buttons in window: {len(buttons)})")
        
        # Show some example buttons for debugging
        if buttons and not action_buttons:
            print("      Sample buttons found:")
            for btn in buttons[:5]:
                r = btn['rect']
                has_bounds = r.right > r.left and r.bottom > r.top
                print(f"        - \"{btn['name'][:40]}...\" visible={has_bounds} depth={btn['depth']}")

if __name__ == "__main__":
    main()
