"""Quick test of the updated button finder"""
from automation.ui.button_finder import find_all_allow_buttons_in_window
from automation.config import ALL_ACTION_BUTTON_NAMES
import pyvda
import uiautomation as auto
import time

# Switch to TF
for d in pyvda.get_virtual_desktops():
    if d.name == 'TF':
        d.go()
        break

time.sleep(0.5)

# Find VS Code windows
windows = []
for w in auto.GetRootControl().GetChildren():
    try:
        name = w.Name or ''
        if name.endswith(' - Visual Studio Code'):
            windows.append(w)
    except:
        pass

print(f'Found {len(windows)} VS Code windows on TF')

# Try finding buttons in first 5 windows
for i, win in enumerate(windows[:5], 1):
    title = (win.Name or 'Unknown')[:50]
    print(f'[{i}] {title}...')
    buttons = find_all_allow_buttons_in_window(win)
    print(f'    Found {len(buttons)} action button(s)')
    for btn in buttons:
        name = btn.Name or ''
        rect = btn.BoundingRectangle
        print(f'    - "{name}" at ({rect.left},{rect.top})')
