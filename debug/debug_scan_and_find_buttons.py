"""Quick debug script to scan TF and Trading desktops for Allow buttons"""
import time
import pyvda
import uiautomation as auto
from automation.config import ALLOW_BUTTON_NAMES, ALL_ACTION_BUTTON_NAMES, VSCODE_TITLE_SUFFIX

def get_current_desktop_name():
    """Get current desktop name."""
    try:
        return pyvda.VirtualDesktop.current().name
    except Exception:
        return None

def switch_to_desktop(name):
    """Switch to desktop by name."""
    try:
        desktops = pyvda.get_virtual_desktops()
        for d in desktops:
            if d.name == name:
                print(f"  Switching to {name}...")
                d.go()
                time.sleep(0.5)
                return True
        print(f"  Desktop '{name}' not found!")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

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
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
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
        except Exception:
            pass
    
    search(vs_win)
    return buttons

def main():
    print("=" * 70)
    print("BUTTON SCANNER - Checking TF and Trading Desktops")
    print("=" * 70)
    print()
    
    original_desktop = get_current_desktop_name()
    print(f"Starting from desktop: {original_desktop}")
    print()
    
    desktops_to_check = ["TF", "Trading"]
    
    for desktop in desktops_to_check:
        print(f"\n{'='*70}")
        print(f"DESKTOP: {desktop}")
        print(f"{'='*70}")
        
        if not switch_to_desktop(desktop):
            continue
        
        current = get_current_desktop_name()
        print(f"  Current desktop is now: {current}")
        
        time.sleep(0.5)
        
        windows = find_vscode_windows()
        print(f"  Found {len(windows)} VS Code window(s)")
        
        for i, win in enumerate(windows, 1):
            title = (win.Name or "Unknown")[:60]
            print(f"\n  [{i}] {title}")
            
            buttons = find_all_buttons_deep(win)
            
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
                    print(f"        - \"{btn['name'][:40]}...\" visible={has_bounds}")
    
    print(f"\n{'='*70}")
    print(f"Returning to original desktop: {original_desktop}")
    if original_desktop:
        switch_to_desktop(original_desktop)
    print("Done.")

if __name__ == "__main__":
    main()
