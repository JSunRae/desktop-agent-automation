"""Test: What happens when we press left multiple times from different starting positions"""
import time
import keyboard
import uiautomation as auto

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

def find_windows():
    windows = []
    try:
        for w in auto.GetRootControl().GetChildren():
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(0.5):
                            windows.append(w)
                except Exception:
                    continue
    except Exception:
        pass
    return len(windows)

print("Testing navigation behavior")
print("="*60)

# Test 1: Go left many times, then right 5 times
print("\nTest 1: Left 10x, wait, Right 5x")
for _ in range(10):
    keyboard.send('win+ctrl+left')
    time.sleep(0.15)
time.sleep(3)
print(f"  After left 10x: {find_windows()} windows")

for _ in range(5):
    keyboard.send('win+ctrl+right')
    time.sleep(0.25)
time.sleep(3)
print(f"  After right 5x: {find_windows()} windows")

# Test 2: From here, try right 4 times to go to desktop 5
print("\nTest 2: From current, Left 10x, Right 4x (for desktop 5)")
for _ in range(10):
    keyboard.send('win+ctrl+left')
    time.sleep(0.15)
time.sleep(3)
print(f"  After left 10x: {find_windows()} windows")

for _ in range(4):
    keyboard.send('win+ctrl+right')
    time.sleep(0.25)
time.sleep(3)
print(f"  After right 4x: {find_windows()} windows")

# Test 3: Try navigating directly right from desktop 5 to 6
print("\nTest 3: From current (should be 5), Right 1x")
keyboard.send('win+ctrl+right')
time.sleep(3)
print(f"  After right 1x: {find_windows()} windows")

print("\n" + "="*60)
print("Done")
