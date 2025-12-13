"""
Debug script to test pyvda desktop switching with names.
"""
import pyvda
import uiautomation as auto
import time

DESKTOPS_TO_CHECK = ['TF', 'Trading']

print('=== Testing pyvda desktop switching ===')
print()

for desktop_name in DESKTOPS_TO_CHECK:
    print(f'Switching to desktop "{desktop_name}"...')
    
    # Find desktop by name
    target = None
    for d in pyvda.get_virtual_desktops():
        if d.name == desktop_name:
            target = d
            break
    
    if target is None:
        print(f'  ERROR: Desktop "{desktop_name}" not found!')
        continue
    
    # Switch to it
    target.go()
    time.sleep(0.5)
    
    # Verify we switched
    current = pyvda.VirtualDesktop.current()
    print(f'  Now on: "{current.name}"')
    
    # Count VS Code windows
    vscode_count = 0
    for w in auto.GetRootControl().GetChildren():
        try:
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                name = w.Name or ''
                if 'Visual Studio Code' in name:
                    vscode_count += 1
        except:
            pass
    print(f'  VS Code windows: {vscode_count}')
    print()

print('=== Test complete ===')
