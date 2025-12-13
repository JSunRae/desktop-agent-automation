"""Test desktop switching reliability"""
import time
import keyboard
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"
MAX_DESKTOPS_TO_SCAN = 10
DESKTOP_SCAN_WAIT = 5

def find_all_vscode_windows(timeout: float = 0.5) -> list:
    """Find ALL VS Code windows by title suffix."""
    vscode_windows = []
    try:
        for w in auto.GetRootControl().GetChildren():
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(timeout):
                            vscode_windows.append(w)
                except Exception:
                    continue
    except Exception as e:
        print(f"  Warning: {e}")
    return vscode_windows

def switch_to_desktop(desktop_number: int):
    """Switch to desktop using keyboard shortcuts"""
    # Release any held keys first
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.2)
    
    # Go to desktop 1
    print(f"    [Going to desktop 1...]")
    for i in range(MAX_DESKTOPS_TO_SCAN):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    
    time.sleep(0.5)
    
    # Navigate to target
    print(f"    [Navigating to desktop {desktop_number}...]")
    for i in range(desktop_number - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.25)
    
    # Wait for desktop switch and UI tree update
    time.sleep(DESKTOP_SCAN_WAIT)
    time.sleep(1)  # Additional wait for Chrome UI tree

def test_switch():
    print("="*60)
    print("Desktop Switching Test")
    print("="*60)
    
    # First, see what's on current desktop
    print("\nCurrent desktop:")
    windows = find_all_vscode_windows()
    print(f"  Found {len(windows)} VS Code windows")
    
    # Test switching to desktops 5 and 6
    for target in [5, 6, 5, 6]:
        print(f"\n--- Switching to desktop {target} ---")
        switch_to_desktop(target)
        
        # Retry finding windows a few times
        for attempt in range(3):
            windows = find_all_vscode_windows()
            if windows:
                break
            print(f"    (retry {attempt+1}...)")
            time.sleep(1)
        
        print(f"  After switch: Found {len(windows)} VS Code windows")
        
        if windows:
            for i, w in enumerate(windows[:3], 1):
                title = (w.Name or "")[:50]
                print(f"    {i}. {title}...")
        
        time.sleep(0.5)
    
    print("\n" + "="*60)
    print("Test complete")
    print("="*60)

if __name__ == "__main__":
    test_switch()
