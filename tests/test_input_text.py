"""Quick test to check text in chat input boxes."""

from automation.panel_tracker import (
    find_chat_editor_control,
    _check_editor_has_text_via_clipboard,
)
import uiautomation as auto
import time
import ctypes

# Find VS Code windows
windows = []
for w in auto.GetRootControl().GetChildren():
    if isinstance(w, (auto.WindowControl, auto.PaneControl)):
        try:
            name = w.Name
            if name and name.endswith(' - Visual Studio Code'):
                if w.Exists(0.5):
                    windows.append(w)
        except Exception:
            continue

print(f'Found {len(windows)} VS Code windows')

# Check each window's input state
for i, w in enumerate(windows, 1):
    title = w.Name[:50]
    print(f'\nWindow {i}: {title}...')
    
    # Find editor
    editor = find_chat_editor_control(w)
    if not editor:
        print('  No editor found')
        continue
    
    # Save current window
    original_window = ctypes.windll.user32.GetForegroundWindow()
    
    try:
        # Activate and focus
        w.SetActive()
        time.sleep(0.15)
        editor.SetFocus()
        time.sleep(0.1)
        
        # Check for text
        has_text, text = _check_editor_has_text_via_clipboard(editor)
        
        print(f'  Has text: {has_text}')
        if has_text:
            print(f'  Text: "{text[:80]}"')
        else:
            print('  Text: (empty)')
    finally:
        if original_window:
            time.sleep(0.1)
            ctypes.windll.user32.SetForegroundWindow(original_window)
