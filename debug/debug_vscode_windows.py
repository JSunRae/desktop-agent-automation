"""
Debug script to understand why VS Code windows are not being detected.
"""
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

print("Checking all top-level controls...")
print("-" * 80)

vscode_windows = []

for w in auto.GetRootControl().GetChildren():
    try:
        name = w.Name
        ctype = type(w).__name__
        is_window = isinstance(w, auto.WindowControl)
        is_pane = isinstance(w, auto.PaneControl)
        
        if name:
            match_suffix = name.endswith(VSCODE_TITLE_SUFFIX)
            print(f"[{ctype}] {name[:70]}")
            print(f"    -> WindowControl: {is_window}, PaneControl: {is_pane}, Suffix match: {match_suffix}")
            
            if match_suffix and (is_window or is_pane):
                try:
                    exists = w.Exists(0.5)
                    print(f"    -> Exists check: {exists}")
                    if exists:
                        vscode_windows.append(w)
                        print(f"    -> ADDED TO LIST!")
                except Exception as e:
                    print(f"    -> Exists check failed: {e}")
    except Exception as e:
        print(f"Error reading control: {e}")

print("-" * 80)
print(f"\nTotal VS Code windows found: {len(vscode_windows)}")

if vscode_windows:
    print("\nVS Code windows:")
    for i, w in enumerate(vscode_windows):
        print(f"  {i+1}. {w.Name}")
else:
    print("\nNo VS Code windows were found!")
    print("\nPossible issues:")
    print("  1. VS Code windows might be on a different virtual desktop")
    print("  2. The window title suffix might have changed")
    print("  3. UI Automation might not be able to see the windows")
