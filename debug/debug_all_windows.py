"""Debug: Check ALL windows (not just VS Code) for Allow buttons"""
import uiautomation as auto
import keyboard
import time

def switch_to_desktop(desktop_number):
    """Switch to a specific virtual desktop"""
    keyboard.release('ctrl')
    keyboard.release('shift')
    keyboard.release('alt')
    keyboard.release('win')
    time.sleep(0.2)
    
    for i in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.3)
    time.sleep(1)
    
    for i in range(desktop_number - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.3)
    time.sleep(2)

def find_buttons_with_text(root_control, text_pattern, max_depth=50):
    """Find buttons containing specific text pattern"""
    found = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            control_type = control.ControlType
            name = control.Name or ""
            
            if text_pattern.lower() in name.lower():
                rect = control.BoundingRectangle
                found.append({
                    'name': name[:100],
                    'type': control_type,
                    'rect': f"({rect.left},{rect.top})-({rect.right},{rect.bottom})",
                    'control': control
                })
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(root_control)
    return found

print("="*80)
print("CHECKING ALL TOP-LEVEL WINDOWS FOR 'ALLOW' CONTROLS")
print("="*80)

switch_to_desktop(2)
time.sleep(1)

# Get root control and check ALL windows
root = auto.GetRootControl()

print("\nAll top-level windows on desktop 2:")
print("-"*80)

all_windows = []
for win in root.GetChildren():
    try:
        name = win.Name or "(no name)"
        class_name = win.ClassName or ""
        rect = win.BoundingRectangle
        
        # Filter to visible windows
        if rect.right > rect.left and rect.bottom > rect.top:
            all_windows.append(win)
            print(f"  [{win.ControlType}] '{name[:60]}'")
            print(f"    Class: {class_name}, Rect: ({rect.left},{rect.top})")
    except Exception:
        pass

print(f"\nTotal: {len(all_windows)} visible windows")

# Now search ALL windows for "Allow" or "Keep" buttons
print("\n" + "="*80)
print("SEARCHING ALL WINDOWS FOR ALLOW/KEEP")
print("="*80)

for text in ['Allow', 'Keep']:
    print(f"\nSearching for '{text}'...")
    for win in all_windows:
        try:
            results = find_buttons_with_text(win, text)
            if results:
                win_name = (win.Name or "Unknown")[:50]
                print(f"  Found in window: {win_name}")
                for r in results:
                    print(f"    [{r['type']}] '{r['name'][:60]}' at {r['rect']}")
        except Exception as e:
            pass

print("\n" + "="*80)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("Done.")
