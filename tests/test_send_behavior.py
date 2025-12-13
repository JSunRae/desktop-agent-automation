"""
Test the updated send_text_to_chat behavior.

When the chat input:
1. Has focus AND has text -> Should NOT send (skip)
2. Has focus AND is empty -> Should send (OK)
3. Does NOT have focus -> Should send (OK, will activate and type)

This test checks behavior 1 and 2 by clicking in the chat input.
"""
import uiautomation as auto
import ctypes
import sys
sys.path.insert(0, r"c:\Users\Pilot\Documents\Vs Code Projects\desktop-agent-automation")

from automation.panel_tracker import (
    find_chat_editor_control,
    send_text_to_chat,
    _check_editor_has_text_via_clipboard,
)

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"


def find_all_vscode_windows():
    """Find all VS Code windows."""
    vscode_windows = []
    for w in auto.GetRootControl().GetChildren():
        if isinstance(w, (auto.WindowControl, auto.PaneControl)):
            try:
                name = w.Name
                if name and name.endswith(VSCODE_TITLE_SUFFIX):
                    if w.Exists(0.5):
                        vscode_windows.append(w)
            except Exception:
                continue
    return vscode_windows


def main():
    print("=" * 70)
    print("Testing send_text_to_chat with text detection")
    print("=" * 70)
    print()
    print("This test will check if your chat input has text.")
    print("If you're clicked in a chat input WITH text, it should skip sending.")
    print()
    
    windows = find_all_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s)")
    
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    for w in windows[:2]:
        try:
            is_foreground = w.NativeWindowHandle == hwnd
        except Exception:
            is_foreground = False
        
        title = w.Name or "Unknown"
        fg_marker = " [FOREGROUND]" if is_foreground else ""
        print(f"\nWindow: {title[:50]}...{fg_marker}")
        print("-" * 60)
        
        # Find chat editor
        editor = find_chat_editor_control(w)
        if not editor:
            print("  No chat editor found")
            continue
        
        rect = editor.BoundingRectangle
        print(f"  Found editor at ({rect.left}, {rect.top}), {rect.width()}x{rect.height()}")
        
        # Check focus
        try:
            has_focus = editor.HasKeyboardFocus
            print(f"  HasKeyboardFocus: {has_focus}")
        except Exception as e:
            print(f"  Focus check error: {e}")
            continue
        
        if has_focus:
            # Check for text via clipboard
            print("  --> Editor has focus, checking for text...")
            has_text, existing_text = _check_editor_has_text_via_clipboard(editor)
            if has_text:
                print(f"  *** FOUND TEXT: '{existing_text[:60]}...'")
                print("  --> send_text_to_chat would SKIP this panel")
            else:
                print("  --> Editor is EMPTY")
                print("  --> send_text_to_chat would PROCEED")
        else:
            print("  --> Editor does NOT have focus")
            print("  --> send_text_to_chat would PROCEED (will activate window)")
    
    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
