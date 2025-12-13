"""Scan current desktop only - no switching"""
import uiautomation as auto
import time

print("Scanning current desktop for VS Code windows...")
print("=" * 60)

# Get all top-level windows
root = auto.GetRootControl()
all_windows = []
vscode_windows = []

for w in root.GetChildren():
    try:
        name = w.Name or ""
        all_windows.append(name[:60])
        if " - Visual Studio Code" in name:
            vscode_windows.append(w)
    except Exception as e:
        pass

print(f"Total top-level windows: {len(all_windows)}")
print(f"VS Code windows: {len(vscode_windows)}")

if vscode_windows:
    print("\nVS Code windows found:")
    for w in vscode_windows:
        print(f"  - {w.Name[:60]}")
else:
    print("\nNo VS Code windows found on this desktop.")
    print("\nAll top-level windows:")
    for n in all_windows[:20]:
        if n:
            print(f"  - {n}")

# Search for action buttons in any VS Code window
if vscode_windows:
    print("\n" + "=" * 60)
    print("SEARCHING FOR ACTION BUTTONS")
    print("=" * 60)
    
    action_patterns = ['Allow', 'Keep', 'Retry', 'Accept', 'Confirm', 'Continue', 'Try Again']
    
    for win in vscode_windows:
        print(f"\nWindow: {win.Name[:55]}")
        found_buttons = []
        
        def search(ctrl, depth=0):
            if depth > 50:
                return
            try:
                ct = ctrl.ControlType
                name = ctrl.Name or ''
                
                if ct in [50000, 50031] and name:  # Button or SplitButton
                    if any(p in name for p in action_patterns):
                        if name not in ['Minimize', 'Maximize', 'Restore', 'Close']:
                            found_buttons.append((name, depth))
                
                for child in ctrl.GetChildren():
                    search(child, depth + 1)
            except:
                pass
        
        search(win)
        
        if found_buttons:
            print(f"  Found {len(found_buttons)} action button(s):")
            for name, d in found_buttons:
                print(f"    - '{name}' (depth {d})")
        else:
            print("  No action buttons found in this window")
