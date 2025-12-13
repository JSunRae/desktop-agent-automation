"""Debug script to find ALL controls in VS Code windows - detailed dump"""
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

def dump_all_controls(vs_win, max_depth=30, output_file=None):
    """Dump all controls in a VS Code window"""
    lines = []
    
    def format_control(control, depth):
        indent = "  " * depth
        try:
            name = (control.Name or "")[:80].replace('\n', '\\n')
            control_type = control.ControlType
            class_name = control.ClassName or ""
            rect = control.BoundingRectangle
            auto_id = getattr(control, 'AutomationId', '') or ''
            
            # Map control type ID to name
            type_names = {
                50000: 'Button',
                50001: 'Calendar',
                50002: 'CheckBox', 
                50003: 'ComboBox',
                50004: 'Edit',
                50005: 'Hyperlink',
                50006: 'Image',
                50007: 'ListItem',
                50008: 'List',
                50009: 'Menu',
                50010: 'MenuBar',
                50011: 'MenuItem',
                50012: 'ProgressBar',
                50013: 'RadioButton',
                50014: 'ScrollBar',
                50015: 'Slider',
                50016: 'Spinner',
                50017: 'StatusBar',
                50018: 'Tab',
                50019: 'TabItem',
                50020: 'Text',
                50021: 'ToolBar',
                50022: 'ToolTip',
                50023: 'Tree',
                50024: 'TreeItem',
                50025: 'Custom',
                50026: 'Group',
                50027: 'Thumb',
                50028: 'DataGrid',
                50029: 'DataItem',
                50030: 'Document',
                50031: 'SplitButton',
                50032: 'Window',
                50033: 'Pane',
                50034: 'Header',
                50035: 'HeaderItem',
                50036: 'Table',
                50037: 'TitleBar',
                50038: 'Separator',
            }
            type_name = type_names.get(control_type, f'Unknown({control_type})')
            
            line = f"{indent}[{type_name}] '{name[:60]}'"
            if class_name:
                line += f" (class={class_name[:30]})"
            if auto_id:
                line += f" (id={auto_id[:30]})"
                
            return line
        except Exception as e:
            return f"{indent}[ERROR: {e}]"
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            line = format_control(control, depth)
            lines.append(line)
            
            # Check for interesting patterns
            name = (control.Name or "").lower()
            if 'allow' in name or 'keep' in name or 'skip' in name:
                lines.append(f"{'  ' * depth}  *** INTERESTING: Contains action keyword! ***")
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    return lines

def switch_to_desktop(desktop_number):
    """Switch to a specific virtual desktop"""
    for i in range(10):
        keyboard.send('win+ctrl+left')
        time.sleep(0.15)
    time.sleep(0.3)
    for i in range(desktop_number - 1):
        keyboard.send('win+ctrl+right')
        time.sleep(0.15)
    time.sleep(0.5)

print("Switching to desktop 2 where you have the TF windows...")
switch_to_desktop(2)
time.sleep(1)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)")

if windows:
    # Look for a TF window with an Allow button visible
    for i, win in enumerate(windows):
        title = win.Name or "Unknown"
        if 'tf' in title.lower() or 'trading' in title.lower():
            print(f"\nDumping controls from: {title[:70]}...")
            output_file = f"debug_controls_tf_{i}.txt"
            lines = dump_all_controls(win, max_depth=40, output_file=output_file)
            print(f"Saved {len(lines)} controls to {output_file}")
            
            # Show any lines with "allow" or "keep"
            print("\nLines containing 'allow' or 'keep' or 'skip':")
            for line in lines:
                if 'allow' in line.lower() or 'keep' in line.lower() or 'skip' in line.lower():
                    print(line)
            break
    else:
        # Just dump the first window
        print(f"\nNo TF window found, dumping first window: {windows[0].Name[:70]}...")
        output_file = "debug_controls_first.txt"
        lines = dump_all_controls(windows[0], max_depth=40, output_file=output_file)
        print(f"Saved {len(lines)} controls to {output_file}")

print("\nDone. Returning to desktop 1...")
switch_to_desktop(1)
