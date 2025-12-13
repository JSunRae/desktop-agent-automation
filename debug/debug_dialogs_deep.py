"""Debug: Look for dialogs, menus, and controls with 'Chat Confirmation' patterns"""
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

def dump_all_controls_with_types(vs_win, max_depth=70, file_handle=None):
    """Dump ALL controls with their full type info"""
    type_names = {
        50000: 'Button', 50001: 'Calendar', 50002: 'CheckBox', 
        50003: 'ComboBox', 50004: 'Edit', 50005: 'Hyperlink',
        50006: 'Image', 50007: 'ListItem', 50008: 'List',
        50009: 'Menu', 50010: 'MenuBar', 50011: 'MenuItem',
        50012: 'ProgressBar', 50013: 'RadioButton', 50014: 'ScrollBar',
        50015: 'Slider', 50016: 'Spinner', 50017: 'StatusBar',
        50018: 'Tab', 50019: 'TabItem', 50020: 'Text',
        50021: 'ToolBar', 50022: 'ToolTip', 50023: 'Tree',
        50024: 'TreeItem', 50025: 'Custom', 50026: 'Group',
        50027: 'Thumb', 50028: 'DataGrid', 50029: 'DataItem',
        50030: 'Document', 50031: 'SplitButton', 50032: 'Window',
        50033: 'Pane', 50034: 'Header', 50035: 'HeaderItem',
        50036: 'Table', 50037: 'TitleBar', 50038: 'Separator',
    }
    
    interesting_controls = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            control_type = control.ControlType
            name = control.Name or ""
            auto_id = getattr(control, 'AutomationId', '') or ''
            class_name = control.ClassName or ""
            rect = control.BoundingRectangle
            
            type_name = type_names.get(control_type, f'Unknown({control_type})')
            
            # Check for interesting patterns
            name_lower = name.lower()
            auto_id_lower = auto_id.lower()
            
            is_interesting = False
            reason = ""
            
            # Look for dialog/confirmation patterns
            if 'dialog' in name_lower or 'confirmation' in name_lower:
                is_interesting = True
                reason = "dialog/confirmation"
            elif 'allow' in name_lower or 'keep' in name_lower or 'skip' in name_lower:
                is_interesting = True
                reason = "action keyword"
            elif 'inline' in name_lower and 'chat' in name_lower:
                is_interesting = True
                reason = "inline chat"
            elif control_type == 50026:  # Group
                if name and len(name) < 100:
                    is_interesting = True
                    reason = "group with name"
            elif 'workbench.action' in auto_id_lower:
                is_interesting = True
                reason = "workbench action"
            
            if is_interesting:
                indent = "  " * depth
                line = f"{indent}[{type_name}] '{name[:100]}'"
                if auto_id:
                    line += f"\n{indent}  AutomationId: {auto_id}"
                if class_name:
                    line += f"\n{indent}  ClassName: {class_name}"
                line += f"\n{indent}  Rect: ({rect.left},{rect.top})-({rect.right},{rect.bottom})"
                line += f"\n{indent}  Reason: {reason}"
                
                interesting_controls.append(line)
                if file_handle:
                    file_handle.write(line + "\n\n")
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return interesting_controls

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

print("="*80)
print("LOOKING FOR DIALOGS AND CONFIRMATION CONTROLS")
print("="*80)

switch_to_desktop(2)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)")

with open("debug_interesting_controls.txt", "w", encoding="utf-8") as f:
    for i, win in enumerate(windows, 1):
        title = (win.Name or "Unknown")[:60]
        print(f"\n[{i}] {title}...")
        f.write(f"\n{'='*80}\n")
        f.write(f"Window: {title}\n")
        f.write("="*80 + "\n\n")
        
        controls = dump_all_controls_with_types(win, file_handle=f)
        
        print(f"  Found {len(controls)} interesting control(s)")
        
        # Print first few
        for ctrl in controls[:5]:
            # Just print first line
            first_line = ctrl.split('\n')[0]
            print(f"    {first_line[:70]}...")

print("\nFull dump saved to debug_interesting_controls.txt")

print("\n" + "="*80)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("Done.")
