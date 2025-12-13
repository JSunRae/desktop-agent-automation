"""Debug script to dump ALL controls at bottom of chat windows"""
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

def dump_clickable_controls(vs_win, max_depth=60):
    """Find all potentially clickable controls"""
    clickable = []
    
    # Control types that are typically clickable
    CLICKABLE_TYPES = {
        50000: 'Button',
        50005: 'Hyperlink', 
        50011: 'MenuItem',
        50031: 'SplitButton',
        50025: 'Custom',  # Often used for custom buttons
    }
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            control_type = control.ControlType
            name = control.Name or ""
            
            # Check if it's a clickable type OR if it has a short name (like a button label)
            if control_type in CLICKABLE_TYPES:
                rect = control.BoundingRectangle
                # Only include if has valid bounds (is visible)
                if rect.right > rect.left and rect.bottom > rect.top:
                    clickable.append({
                        'name': name[:80],
                        'type': CLICKABLE_TYPES.get(control_type, f'Type{control_type}'),
                        'rect': rect,
                        'control': control
                    })
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return clickable

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
print("DUMPING ALL CLICKABLE CONTROLS")
print("="*80)

switch_to_desktop(2)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s) on desktop 2")

if windows:
    # Focus on the TF window if there is one
    target_win = None
    for win in windows:
        title = (win.Name or "").lower()
        if 'tf' in title or 'trading' in title:
            target_win = win
            break
    
    if not target_win:
        target_win = windows[0]
    
    print(f"\nAnalyzing: {target_win.Name[:60]}...")
    print("-"*80)
    
    # Get all clickable controls
    clickables = dump_clickable_controls(target_win)
    
    print(f"Found {len(clickables)} clickable controls")
    print("\nButtons and SplitButtons:")
    for c in clickables:
        if c['type'] in ['Button', 'SplitButton']:
            r = c['rect']
            print(f"  [{c['type']}] '{c['name'][:60]}' at ({r.left},{r.top})-({r.right},{r.bottom})")
    
    print("\nCustom controls (may be buttons):")
    for c in clickables:
        if c['type'] == 'Custom':
            r = c['rect']
            # Only show if name is short (button-like)
            if len(c['name']) < 50:
                print(f"  [{c['type']}] '{c['name']}' at ({r.left},{r.top})-({r.right},{r.bottom})")

    # Also try to find the Chat panel specifically
    print("\n" + "-"*80)
    print("Looking for Chat panel...")
    
    def find_chat_panel(control, depth=0, max_depth=20):
        if depth > max_depth:
            return None
        try:
            name = (control.Name or "").lower()
            if 'chat' in name and control.ControlType == auto.ControlType.PaneControl:
                return control
            for child in control.GetChildren():
                result = find_chat_panel(child, depth + 1)
                if result:
                    return result
        except Exception:
            pass
        return None
    
    chat_panel = find_chat_panel(target_win)
    if chat_panel:
        print(f"Found chat panel: {chat_panel.Name[:60] if chat_panel.Name else 'unnamed'}")
        
        # Dump buttons in chat panel specifically  
        clickables_in_chat = dump_clickable_controls(chat_panel, max_depth=40)
        print(f"Clickable controls in chat panel: {len(clickables_in_chat)}")
        for c in clickables_in_chat:
            r = c['rect']
            print(f"  [{c['type']}] '{c['name'][:50]}' at ({r.left},{r.top})")
    else:
        print("Chat panel not found")

print("\n" + "="*80)
print("Returning to desktop 1...")
switch_to_desktop(1)
print("Done.")
