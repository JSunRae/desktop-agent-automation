"""
Test script to check if the chat input box has text using TextPattern.
"""
import uiautomation as auto
import subprocess
import ctypes
from typing import Optional, List

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


def find_chat_editor_control(vs_win) -> Optional[auto.Control]:
    """
    Find the chat input editor control in a VS Code window.
    """
    found_editors: List[auto.Control] = []
    
    def search_for_editor(control, depth=0, max_depth=50):
        if depth > max_depth:
            return
        
        try:
            # Look for EditControl with the specific accessibility name
            if control.ControlType == auto.ControlType.EditControl:
                name = control.Name or ""
                # VS Code chat input has this specific accessibility message
                if "editor is not accessible" in name.lower() or "screen reader" in name.lower():
                    if control.Exists(0.1):
                        found_editors.append(control)
                        return  # Found it
            
            for child in control.GetChildren():
                search_for_editor(child, depth + 1, max_depth)
                if found_editors:
                    return  # Stop if found
        except Exception:
            pass
    
    search_for_editor(vs_win)
    return found_editors[0] if found_editors else None


def get_text_via_patterns(editor) -> Optional[str]:
    """Try to get text using UI Automation patterns."""
    
    # Try TextPattern
    print("    Trying TextPattern...")
    try:
        text_pattern = editor.GetTextPattern()
        if text_pattern:
            doc_range = text_pattern.DocumentRange
            if doc_range:
                text = doc_range.GetText(-1)  # -1 means get all text
                print(f"    TextPattern result: '{text[:100] if text else ''}...'")
                if text and text.strip():
                    return text.strip()
    except Exception as e:
        print(f"    TextPattern error: {e}")
    
    # Try ValuePattern
    print("    Trying ValuePattern...")
    try:
        value_pattern = editor.GetValuePattern()
        if value_pattern:
            value = value_pattern.Value
            print(f"    ValuePattern result: '{value[:100] if value else ''}'")
            if value and value.strip():
                return value.strip()
    except Exception as e:
        print(f"    ValuePattern error: {e}")
    
    # Try LegacyIAccessible
    print("    Trying LegacyIAccessiblePattern...")
    try:
        legacy = editor.GetLegacyIAccessiblePattern()
        if legacy:
            value = legacy.Value
            print(f"    LegacyIAccessible result: '{value[:100] if value else ''}'")
            if value and value.strip():
                return value.strip()
    except Exception as e:
        print(f"    LegacyIAccessible error: {e}")
    
    return None


def get_text_via_clipboard(vs_win, editor) -> Optional[str]:
    """Get text using clipboard method."""
    import time
    
    print("    Trying clipboard method...")
    try:
        original_window = ctypes.windll.user32.GetForegroundWindow()
        
        try:
            # Activate the VS Code window
            vs_win.SetActive()
            time.sleep(0.1)
            
            # Focus the editor
            try:
                editor.SetFocus()
                time.sleep(0.05)
            except Exception:
                pass
            
            # Clear clipboard first
            subprocess.run(
                ["powershell", "-Command", "Set-Clipboard -Value ''"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            time.sleep(0.03)
            
            # Select all text in the input box and copy to clipboard
            auto.SendKeys("^a")  # Ctrl+A to select all
            time.sleep(0.05)
            auto.SendKeys("^c")  # Ctrl+C to copy
            time.sleep(0.05)
            
            # Get clipboard content using PowerShell
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # Deselect by pressing End (to preserve cursor position)
            auto.SendKeys("{End}")
            time.sleep(0.02)
            
            clipboard_text = result.stdout.strip() if result.returncode == 0 else ""
            print(f"    Clipboard result: '{clipboard_text[:100] if clipboard_text else ''}'")
            return clipboard_text
            
        finally:
            # Restore original window
            if original_window:
                time.sleep(0.05)
                ctypes.windll.user32.SetForegroundWindow(original_window)
                
    except Exception as e:
        print(f"    Clipboard error: {e}")
        return None


def main():
    print("=" * 60)
    print("Testing Chat Input Box Text Detection (TextPattern)")
    print("=" * 60)
    
    # Find VS Code windows on current desktop
    print("\nSearching for VS Code windows...")
    windows = find_all_vscode_windows()
    
    if not windows:
        print("No VS Code windows found on this desktop!")
        return
    
    print(f"Found {len(windows)} VS Code window(s):\n")
    
    for i, win in enumerate(windows, 1):
        title = win.Name or "Unknown"
        print(f"\n[Window {i}] {title[:60]}...")
        print("-" * 50)
        
        # Find the chat editor control
        print("Looking for chat editor control...")
        editor = find_chat_editor_control(win)
        
        if not editor:
            print("  ❌ Chat editor control not found")
            continue
        
        print(f"  ✓ Found editor: {editor.Name[:60]}...")
        print(f"    BoundingRectangle: {editor.BoundingRectangle}")
        
        # Try UI Automation patterns first
        print("\n  Attempting to read text...")
        text = get_text_via_patterns(editor)
        
        if text is None:
            # Fallback to clipboard
            text = get_text_via_clipboard(win, editor)
        
        print("\n  RESULT:")
        if text:
            print(f"  ✓ Found text in input box!")
            print(f"    Content: '{text}'")
            print(f"    Length: {len(text)} chars")
            print("  → send_text_to_chat() would SKIP sending")
        else:
            print("  ✓ Chat input box is empty")
            print("  → send_text_to_chat() would send the message")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
