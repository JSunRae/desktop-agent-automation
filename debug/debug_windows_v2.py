"""
Debug script using multiple methods to find windows.
"""
import uiautomation as auto
import time

print("Method 1: Getting root control children...")
root = auto.GetRootControl()
print(f"Root control: {root}")
print(f"Root Name: {root.Name}")

children = root.GetChildren()
print(f"\nNumber of children: {len(children)}")

print("\nFirst 10 children:")
for i, child in enumerate(children[:10]):
    try:
        print(f"{i}: Type={type(child).__name__}, Name={child.Name if hasattr(child, 'Name') else 'N/A'}")
    except Exception as e:
        print(f"{i}: Error - {e}")

print("\n" + "="*80)
print("Method 2: Direct WindowControl search...")
try:
    # Try to find any window
    window = auto.WindowControl(searchDepth=1)
    if window.Exists(1):
        print(f"Found a window: {window.Name}")
    else:
        print("WindowControl.Exists() returned False")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "="*80)
print("Method 3: Looking for specific VS Code patterns...")

# Try different VS Code title patterns
patterns = [
    "Visual Studio Code",
    "Code",
    "desktop-agent-automation",
    "auto_allow_copilot.py"
]

for pattern in patterns:
    print(f"\nSearching for pattern: '{pattern}'")
    try:
        win = auto.WindowControl(searchDepth=1, SubName=pattern)
        if win.Exists(0.5):
            print(f"  FOUND: {win.Name}")
        else:
            print(f"  Not found")
    except Exception as e:
        print(f"  Error: {e}")

print("\n" + "="*80)
print("Done!")
