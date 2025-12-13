"""Test if left-press batch is causing issues"""
import time
import keyboard
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

def count_windows():
    count = 0
    try:
        for w in auto.GetRootControl().GetChildren():
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(0.5):
                            count += 1
                except Exception:
                    continue
    except Exception:
        pass
    return count

print("="*60)
print("Testing: Slow batch left, then slow batch right")
print("="*60)

# Method 1: Slow left navigation
print("\n1. Slow left navigation (0.5s between presses)...")
keyboard.release('ctrl')
keyboard.release('shift')
keyboard.release('alt')
keyboard.release('win')
time.sleep(0.2)

for i in range(10):
    keyboard.send('win+ctrl+left')
    time.sleep(0.5)  # Much slower
    
time.sleep(3)
print(f"   At desktop 1: {count_windows()} windows")

# Method 2: Slow right navigation to desktop 5
print("\n2. Slow right navigation to desktop 5...")
for i in range(4):  # 4 = desktop 5
    keyboard.send('win+ctrl+right')
    time.sleep(0.5)  # Much slower
    
time.sleep(3)
print(f"   At desktop 5: {count_windows()} windows")

# Method 3: One more right to desktop 6
print("\n3. One more right to desktop 6...")
keyboard.send('win+ctrl+right')
time.sleep(3)
print(f"   At desktop 6: {count_windows()} windows")

print("\n" + "="*60)
