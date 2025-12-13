"""Debug script to find Allow buttons - uses ControlType check instead of isinstance"""
import uiautomation as auto
import time

# Constants from uiautomation
UIA_ButtonControlTypeId = 0xC350  # 50000

def find_vscode_windows():
    """Find all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name or ""
            if name.endswith(" - Visual Studio Code"):
                windows.append(win)
        except:
            pass
    return windows

def find_buttons_by_controltype(vs_win, max_depth=50):
    """Find all buttons using ControlType check instead of isinstance"""
    found_buttons = []
    found_any = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            # Check ControlType directly instead of isinstance
            control_type = control.ControlType
            name = control.Name or ""
            
            # Log any control with "Allow" in the name regardless of type
            if "Allow" in name:
                found_any.append((name, control_type, control.ClassName, control))
                
            # Check if it's a button by ControlType
            if control_type == auto.ControlType.ButtonControl:
                if "Allow" in name or "Keep" in name or "Ctrl+Enter" in name:
                    found_buttons.append((name, control))
                    print(f"    BUTTON FOUND: '{name}' (ClassName: {control.ClassName})")
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception as e:
            pass
    
    search(vs_win)
    return found_buttons, found_any

print("Finding VS Code windows on current desktop...")
print("="*70)
windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:70]
    print(f"[{i}/{len(windows)}] Window: {title}")
    print("-"*70)
    
    buttons, any_allow = find_buttons_by_controltype(win)
    
    if buttons:
        print(f"  ✓ Found {len(buttons)} Allow/Keep button(s) via ControlType")
    else:
        print("  ✗ No Allow/Keep buttons found via ControlType check")
    
    if any_allow:
        print(f"\n  All controls with 'Allow' in name:")
        for name, ct, cn, ctrl in any_allow:
            rect = ctrl.BoundingRectangle
            print(f"    - Name: '{name}'")
            print(f"      ControlType: {ct}, ClassName: {cn}")
            print(f"      BoundingRect: l={rect.left}, t={rect.top}, r={rect.right}, b={rect.bottom}")
            print(f"      isinstance(ButtonControl): {isinstance(ctrl, auto.ButtonControl)}")
            print()
    
    print()

print("="*70)
print("Done.")
