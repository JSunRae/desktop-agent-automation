"""Quick test to verify VS Code window detection"""
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

def find_vscode_window(timeout: float = 0.5) -> auto.Control | None:
    """Try to find the main VS Code window by title suffix."""
    for w in auto.GetRootControl().GetChildren():
        if isinstance(w, (auto.WindowControl, auto.PaneControl)):
            try:
                name = w.Name
                if name and name.endswith(VSCODE_TITLE_SUFFIX):
                    if w.Exists(timeout):
                        return w
            except Exception:
                continue
    return None

# Test it
print("Looking for VS Code window...")
vs = find_vscode_window()
if vs:
    print(f"✓ Found VS Code: {vs.Name}")
    print(f"  Type: {type(vs).__name__}")
    print(f"  Control Type: {vs.ControlTypeName}")
else:
    print("✗ VS Code window not found")
    print("\nAll windows ending with 'Visual Studio Code':")
    for w in auto.GetRootControl().GetChildren():
        if isinstance(w, (auto.WindowControl, auto.PaneControl)):
            try:
                name = w.Name
                if name and "Visual Studio Code" in name:
                    print(f"  - {name}")
            except Exception:
                pass
