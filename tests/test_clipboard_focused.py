"""
Test clipboard text detection when editor has focus.
Only sends Ctrl+A, Ctrl+C if the editor already has keyboard focus.
"""
import uiautomation as auto
import ctypes
import time


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


def find_chat_editors(vs_win, max_depth=60):
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


def get_clipboard_text():
    """Get current clipboard text."""
    import subprocess
    try:
        result = subprocess.run(
            ['powershell', '-command', 'Get-Clipboard'],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def set_clipboard_text(text):
    """Set clipboard text."""
    import subprocess
    try:
        subprocess.run(
            ['powershell', '-command', f'Set-Clipboard -Value "{text}"'],
            capture_output=True, timeout=2
        )
    except Exception:
        pass


def check_editor_text_via_clipboard(editor):
    """
    Check if editor has text by using clipboard.
    ONLY works if editor already has keyboard focus.
    Returns: (has_text: bool, text: str, error: str or None)
    """
    # First verify the editor has focus
    try:
        if not editor.HasKeyboardFocus:
            return (None, "", "Editor does not have keyboard focus - skipping clipboard check")
    except Exception as e:
        return (None, "", f"Cannot check focus: {e}")
    
    # Save current clipboard
    old_clipboard = get_clipboard_text()
    
    # Clear clipboard with a marker
    marker = "__EMPTY_CHECK_MARKER__"
    set_clipboard_text(marker)
    
    try:
        # Send Ctrl+A (select all) then Ctrl+C (copy)
        # Using SendKeys to the control that has focus
        auto.SendKeys('{Ctrl}a')
        time.sleep(0.05)
        auto.SendKeys('{Ctrl}c')
        time.sleep(0.1)
        
        # Check what's in clipboard now
        new_clipboard = get_clipboard_text()
        
        if new_clipboard == marker:
            # Clipboard unchanged - editor was empty
            return (False, "", None)
        else:
            # Got some text
            return (True, new_clipboard, None)
    finally:
        # Restore old clipboard
        if old_clipboard and old_clipboard != marker:
            set_clipboard_text(old_clipboard)


def main():
    print("=" * 70)
    print("Clipboard Text Detection Test")
    print("=" * 70)
    print()
    print("This test will ONLY use Ctrl+A/Ctrl+C on editors that already have focus.")
    print("Click in a chat input box with some text, then run this test.")
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
        
        editors = find_chat_editors(w)
        print(f"Found {len(editors)} chat editor(s)")
        
        for i, editor in enumerate(editors, 1):
            rect = editor.BoundingRectangle
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if rect.left < -5000 or rect.top < -5000:
                continue
            
            print(f"\n  [Chat Input {i}] at ({rect.left}, {rect.top}), {rect.width()}x{rect.height()}")
            
            # Check HasKeyboardFocus first
            try:
                has_focus = editor.HasKeyboardFocus
                print(f"    HasKeyboardFocus: {has_focus}")
            except Exception as e:
                print(f"    Focus check error: {e}")
                continue
            
            # Only try clipboard if it has focus
            if has_focus:
                print("    --> Editor has focus, checking for text via clipboard...")
                has_text, text, error = check_editor_text_via_clipboard(editor)
                if error:
                    print(f"    Error: {error}")
                elif has_text:
                    print(f"    *** FOUND TEXT: '{text[:80]}{'...' if len(text) > 80 else ''}'")
                else:
                    print(f"    Editor is EMPTY")
            else:
                print("    --> Skipping (no focus)")
    
    print("\n" + "=" * 70)
    print("Test complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
