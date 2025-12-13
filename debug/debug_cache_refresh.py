"""
Debug script to test the _refresh_window_cache function directly.
"""
import sys
sys.path.insert(0, '.')

import time
from datetime import datetime
import uiautomation as auto
import keyboard

# Copy the key functions from auto_allow_copilot.py

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"
DESKTOPS_TO_CHECK = [6, 4]
MAX_DESKTOPS_TO_SCAN = 10

_current_desktop = 1
_desktop_sync_done = False


def switch_to_desktop(desktop_number: int, force_sync: bool = False):
    """Switch to a specific virtual desktop."""
    global _current_desktop, _desktop_sync_done
    
    print(f"  switch_to_desktop({desktop_number}) - current={_current_desktop}, sync_done={_desktop_sync_done}")
    
    try:
        keyboard.release('ctrl')
        keyboard.release('shift')
        keyboard.release('alt')
        keyboard.release('win')
        time.sleep(0.15)
        
        if not _desktop_sync_done or force_sync:
            print("    📍 Syncing to desktop 1...")
            for i in range(MAX_DESKTOPS_TO_SCAN):
                keyboard.send('win+ctrl+left')
                time.sleep(0.15)
            _current_desktop = 1
            _desktop_sync_done = True
            time.sleep(0.8)
            print(f"    Sync complete, now at desktop 1")
        
        if _current_desktop == desktop_number:
            print(f"    Already on desktop {desktop_number}")
            return
        
        if desktop_number > _current_desktop:
            steps = desktop_number - _current_desktop
            print(f"    Moving RIGHT {steps} steps...")
            for i in range(steps):
                keyboard.send('win+ctrl+right')
                time.sleep(0.2)
        elif desktop_number < _current_desktop:
            steps = _current_desktop - desktop_number
            print(f"    Moving LEFT {steps} steps...")
            for i in range(steps):
                keyboard.send('win+ctrl+left')
                time.sleep(0.2)
        
        _current_desktop = desktop_number
        print(f"    Now on desktop {desktop_number}")
        time.sleep(1.5)
        
    except Exception as e:
        print(f"    ERROR in switch_to_desktop: {e}")


def find_all_vscode_windows(timeout: float = 0.5):
    """Find all VS Code windows."""
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
        print(f"    ERROR in find_all_vscode_windows: {e}")
    return vscode_windows


def test_refresh_cache():
    """Test the cache refresh logic."""
    print(f"\n{'='*60}")
    print(f"Testing cache refresh at {datetime.now()}")
    print(f"Desktops to check: {DESKTOPS_TO_CHECK}")
    print(f"{'='*60}\n")
    
    total_found = 0
    
    for desktop_num in DESKTOPS_TO_CHECK:
        print(f"\n--- Checking desktop {desktop_num} ---")
        
        if desktop_num == 0:
            print("  Current desktop - no switch needed")
            vscode_windows = find_all_vscode_windows(timeout=0.5)
        else:
            switch_to_desktop(desktop_num)
            vscode_windows = find_all_vscode_windows(timeout=0.5)
        
        print(f"  Found {len(vscode_windows)} VS Code window(s)")
        for w in vscode_windows:
            print(f"    - {w.Name[:60]}...")
            total_found += 1
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {total_found} VS Code windows found across all desktops")
    print(f"{'='*60}")
    
    return total_found


if __name__ == "__main__":
    try:
        test_refresh_cache()
    except KeyboardInterrupt:
        print("\n\nAborted by user")
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
