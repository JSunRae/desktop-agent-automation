"""Quick test to find Allow buttons in VS Code windows"""
import uiautomation as auto
import time

def find_vscode_windows():
    """Find all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            if win.ClassName == "Chrome_WidgetWin_1":
                name = win.Name or ""
                if "Visual Studio Code" in name or name.endswith(" - Code"):
                    windows.append(win)
        except:
            pass
    return windows

def find_buttons_in_window(vs_win, max_depth=50):
    """Find all buttons in a VS Code window"""
    found = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name or ""
                # Look for ANY button with "Allow" or "Keep" in the name
                if "Allow" in name or "Keep" in name or "Ctrl+Enter" in name:
                    found.append((name, control))
                    print(f"    Found button: '{name}'")
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception as e:
            pass
    
    search(vs_win)
    return found

print("Finding VS Code windows on current desktop...")
windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:60]
    print(f"[{i}/{len(windows)}] Window: {title}")
    print("  Searching for Allow/Keep buttons...")
    buttons = find_buttons_in_window(win)
    if not buttons:
        print("    No Allow/Keep buttons found")
    print()

print("Done.")
