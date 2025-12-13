"""Debug script with longer waits and multiple retries"""
import uiautomation as auto
import keyboard
import time

def find_vscode_windows():
    """Find all VS Code windows"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name or ""
            if name.endswith(" - Visual Studio Code"):
                windows.append(win)
        except Exception:
            pass
    return windows

def switch_to_desktop(desktop_number):
    """Switch to a specific virtual desktop with longer waits"""
    print(f"  Navigating to desktop {desktop_number}...")
    
    # Release any held keys
    keyboard.release('ctrl')
    keyboard.release('shift') 
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.2)
    
    # Go to desktop 1 first
    print("  Going to desktop 1...")
    for i in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.3)
    
    time.sleep(1)  # Longer wait
    
    # Navigate to target desktop
    if desktop_number > 1:
        print(f"  Moving right {desktop_number - 1} times...")
        for i in range(desktop_number - 1):
            keyboard.send('win+ctrl+right')
            time.sleep(0.3)
    
    # Long wait for UI to stabilize
    print("  Waiting for UI to stabilize...")
    time.sleep(2)

print("="*70)
print("DESKTOP SWITCHING DEBUG")
print("="*70)

# First check current desktop
print("\nChecking current desktop (before any switching)...")
windows = find_vscode_windows()
print(f"  Found {len(windows)} VS Code windows")
for w in windows[:3]:
    print(f"    - {w.Name[:60] if w.Name else 'Unknown'}...")

# Now try switching to each desktop
for desktop_num in [2, 3, 4]:
    print(f"\n{'='*70}")
    print(f"SWITCHING TO DESKTOP {desktop_num}")
    print("="*70)
    
    switch_to_desktop(desktop_num)
    
    # Try multiple times with increasing waits
    for attempt in range(1, 4):
        windows = find_vscode_windows()
        print(f"  Attempt {attempt}: Found {len(windows)} VS Code windows")
        
        if windows:
            for w in windows[:5]:
                title = w.Name[:60] if w.Name else 'Unknown'
                print(f"    - {title}...")
            break
        else:
            print(f"    Waiting {attempt}s more...")
            time.sleep(attempt)
    
    if not windows:
        print("  ✗ NO WINDOWS FOUND after all attempts!")

print("\n" + "="*70)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("Done.")
