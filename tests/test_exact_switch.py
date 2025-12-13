"""Direct test using the exact same switch_to_desktop logic as main script"""
import time
import keyboard
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"
MAX_DESKTOPS_TO_SCAN = 10
DESKTOP_SCAN_WAIT = 5

def find_all_vscode_windows(timeout: float = 0.5):
    """Exact copy from main script"""
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
        print(f"  Warning: UI enum error: {e}")
    return vscode_windows

def switch_to_desktop(desktop_number: int):
    """Updated with slower timing"""
    try:
        keyboard.release('ctrl')
        keyboard.release('shift')
        keyboard.release('alt')
        keyboard.release('win')
        time.sleep(0.2)
        
        # Slower timing for reliability
        for i in range(MAX_DESKTOPS_TO_SCAN):
            keyboard.send('win+ctrl+left')
            time.sleep(0.4)
        
        time.sleep(1)
        
        for i in range(desktop_number - 1):
            keyboard.send('win+ctrl+right')
            time.sleep(0.4)
        
        time.sleep(2)
        
    except Exception as e:
        print(f"Error: {e}")

print("Testing switch_to_desktop with exact main script logic")
print("="*60)

# Cycle through desktops 5 and 6 multiple times
for i, target in enumerate([5, 6, 5, 6], 1):
    print(f"\n[{i}] Switching to desktop {target}...")
    switch_to_desktop(target)
    
    # Try multiple times to find windows
    windows = []
    for attempt in range(5):
        windows = find_all_vscode_windows()
        if windows:
            break
        print(f"    Retry {attempt+1}/5...")
        time.sleep(1)
    
    print(f"    Found {len(windows)} VS Code windows")
    if windows and len(windows) > 0:
        print(f"    First: {windows[0].Name[:50]}...")

print("\n" + "="*60)
