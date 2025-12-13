"""Clearer test of desktop navigation"""
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

def nav_left(times):
    for _ in range(times):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    time.sleep(3)  # Wait for switch
    return count_windows()

def nav_right(times):
    for _ in range(times):
        keyboard.send('win+ctrl+right')
        time.sleep(0.15)
    time.sleep(3)  # Wait for switch
    return count_windows()

print("Desktop Navigation Test")
print("Expected: Desktop 5 = 3 windows, Desktop 6 = 20 windows")
print("="*60)

# First, go all the way left to ensure we're at desktop 1
print("\n1. Go left 10x to reach desktop 1...")
count = nav_left(10)
print(f"   Result: {count} windows (should be 0 - desktop 1)")

# Now go right step by step
print("\n2. Navigate right, one step at a time:")
for step in range(1, 8):
    count = nav_right(1)
    print(f"   After right x{step}: {count} windows (desktop {step+1})")
    if count > 0:
        print(f"   ^ Found VS Code windows on desktop {step+1}")

print("\n" + "="*60)
