"""Scan all desktops to find where VS Code windows actually are"""
import time
import keyboard
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"
MAX_DESKTOPS = 10
SCAN_WAIT = 5

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

def scan_all_desktops():
    print("="*60)
    print("Desktop Scan - Finding VS Code windows on each desktop")
    print("="*60)
    
    # First go to desktop 1
    print("\nNavigating to desktop 1...")
    for i in range(MAX_DESKTOPS):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    time.sleep(SCAN_WAIT)
    
    # Now scan each desktop from 1 to MAX_DESKTOPS
    results = {}
    for desktop_num in range(1, MAX_DESKTOPS + 1):
        print(f"\n--- Desktop {desktop_num} ---")
        
        # Wait and retry to find windows
        windows = []
        for attempt in range(3):
            windows = find_all_vscode_windows()
            if windows:
                break
            time.sleep(1)
        
        results[desktop_num] = len(windows)
        print(f"  Found {len(windows)} VS Code windows")
        
        if windows:
            for i, w in enumerate(windows[:3], 1):
                title = (w.Name or "")[:50]
                print(f"    {i}. {title}...")
        
        # Move to next desktop
        if desktop_num < MAX_DESKTOPS:
            keyboard.send('win+ctrl+right')
            time.sleep(SCAN_WAIT)
    
    print("\n" + "="*60)
    print("Summary:")
    for d, count in results.items():
        if count > 0:
            print(f"  Desktop {d}: {count} VS Code windows")
    print("="*60)

if __name__ == "__main__":
    scan_all_desktops()
