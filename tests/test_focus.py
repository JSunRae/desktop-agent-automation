"""
Test to check if we can detect when chat input has keyboard focus.
NO keystrokes will be sent.
"""
import uiautomation as auto
import ctypes
from typing import List

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


def find_chat_editors(vs_win, max_depth=60) -> List[auto.Control]:
    """Find chat input editor controls."""
    found = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        try:
            if control.ControlType == auto.ControlType.EditControl:
                name = control.Name or ""
                if "editor is not accessible" in name.lower():
                    if control.Exists(0.1):
                        found.append(control)
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return found


def main():
    print("=" * 70)
    print("Testing HasKeyboardFocus Detection")
    print("=" * 70)
    print("\nThis test checks if we can detect when the chat input has focus.")
    print("NO keystrokes will be sent.\n")
    print("TIP: Click in the chat input box, then run this test to see")
    print("     if it detects the focus correctly.\n")
    
    windows = find_all_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s)\n")
    
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    for w in windows[:5]:
        try:
            is_foreground = w.NativeWindowHandle == hwnd
        except Exception:
            is_foreground = False
        
        title = w.Name or "Unknown"
        fg_marker = " [FOREGROUND]" if is_foreground else ""
        print(f"\nWindow: {title[:55]}...{fg_marker}")
        print("-" * 60)
        
        editors = find_chat_editors(w)
        if not editors:
            print("  No chat editor found")
            continue
        
        for i, editor in enumerate(editors, 1):
            rect = editor.BoundingRectangle
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if rect.left < -5000 or rect.top < -5000:
                continue
                
            print(f"\n  [Chat Input {i}] at ({rect.left}, {rect.top})")
            
            # Check focus properties
            try:
                has_focus = editor.HasKeyboardFocus
                print(f"    HasKeyboardFocus: {has_focus}")
                
                if has_focus:
                    print("    *** USER IS FOCUSED ON THIS INPUT ***")
                    print("    → send_text_to_chat() would SKIP sending")
                else:
                    print("    → send_text_to_chat() would proceed to send")
            except Exception as e:
                print(f"    HasKeyboardFocus error: {e}")
            
            # Also check if it's focusable
            try:
                is_focusable = editor.IsKeyboardFocusable
                print(f"    IsKeyboardFocusable: {is_focusable}")
            except Exception as e:
                print(f"    IsKeyboardFocusable error: {e}")
    
    print("\n" + "=" * 70)
    print("Done - no keystrokes sent!")
    print("=" * 70)


if __name__ == "__main__":
    main()
