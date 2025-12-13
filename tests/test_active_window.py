"""
Test script to check if the chat input box has text.
This version tests only the ACTIVE VS Code window.
"""
import uiautomation as auto
import subprocess
import ctypes
import time
from typing import Optional, List

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"


def get_foreground_window():
    """Get the currently focused window."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    # Try to find it in the automation tree
    for w in auto.GetRootControl().GetChildren():
        if isinstance(w, (auto.WindowControl, auto.PaneControl)):
            try:
                if w.NativeWindowHandle == hwnd:
                    return w
            except Exception:
                continue
    return None


def find_all_edit_controls(vs_win, max_depth=60) -> List[auto.Control]:
    """Find all EditControl elements in the window."""
    found = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            if control.ControlType == auto.ControlType.EditControl:
                if control.Exists(0.1):
                    found.append(control)
            
            for child in control.GetChildren():
                search(child, depth + 1)
        except Exception:
            pass
    
    search(vs_win)
    return found


def get_text_all_methods(editor) -> dict:
    """Try all methods to get text from an editor control."""
    results = {}
    
    # TextPattern
    try:
        text_pattern = editor.GetTextPattern()
        if text_pattern:
            doc_range = text_pattern.DocumentRange
            if doc_range:
                text = doc_range.GetText(-1)
                results['TextPattern'] = text if text else "(empty)"
            else:
                results['TextPattern'] = "(no DocumentRange)"
        else:
            results['TextPattern'] = "(no pattern)"
    except Exception as e:
        results['TextPattern'] = f"(error: {e})"
    
    # ValuePattern
    try:
        value_pattern = editor.GetValuePattern()
        if value_pattern:
            results['ValuePattern'] = value_pattern.Value if value_pattern.Value else "(empty)"
        else:
            results['ValuePattern'] = "(no pattern)"
    except Exception as e:
        results['ValuePattern'] = f"(error: {e})"
    
    # LegacyIAccessible
    try:
        legacy = editor.GetLegacyIAccessiblePattern()
        if legacy:
            results['LegacyIAccessible.Value'] = legacy.Value if legacy.Value else "(empty)"
            results['LegacyIAccessible.Name'] = legacy.Name[:50] if legacy.Name else "(empty)"
        else:
            results['LegacyIAccessible'] = "(no pattern)"
    except Exception as e:
        results['LegacyIAccessible'] = f"(error: {e})"
    
    # Control.Name
    try:
        results['Name'] = editor.Name[:80] if editor.Name else "(empty)"
    except Exception as e:
        results['Name'] = f"(error: {e})"
    
    return results


def main():
    print("=" * 70)
    print("Testing Chat Input Box - ACTIVE WINDOW ONLY")
    print("=" * 70)
    print("\nPlease ensure your VS Code window with text in chat is FOCUSED.")
    print("Waiting 3 seconds for you to focus it...")
    time.sleep(3)
    
    # Get the foreground window
    foreground = get_foreground_window()
    if foreground:
        title = foreground.Name or "Unknown"
        print(f"\nForeground window: {title[:60]}...")
        
        if not title.endswith(VSCODE_TITLE_SUFFIX):
            print("WARNING: This doesn't appear to be a VS Code window!")
    else:
        print("Could not get foreground window, searching for VS Code...")
        for w in auto.GetRootControl().GetChildren():
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(0.5):
                            foreground = w
                            print(f"Found VS Code: {name[:60]}...")
                            break
                except Exception:
                    continue
    
    if not foreground:
        print("No VS Code window found!")
        return
    
    # Find all edit controls
    print("\n" + "-" * 70)
    print("Searching for EditControl elements...")
    edits = find_all_edit_controls(foreground)
    
    print(f"Found {len(edits)} EditControl(s)\n")
    
    for i, edit in enumerate(edits, 1):
        try:
            name = edit.Name or "(no name)"
            rect = edit.BoundingRectangle
            print(f"\n[EditControl {i}]")
            print(f"  Name: {name[:80]}...")
            print(f"  Bounds: {rect}")
            
            # Check if this looks like the chat input
            if "editor is not accessible" in name.lower():
                print("  *** THIS IS THE CHAT INPUT ***")
                
                print("\n  Reading text using all methods:")
                results = get_text_all_methods(edit)
                for method, value in results.items():
                    print(f"    {method}: {value[:100] if isinstance(value, str) else value}")
                
                # Try clipboard method
                print("\n  Trying clipboard method (will select all and copy)...")
                original_window = ctypes.windll.user32.GetForegroundWindow()
                try:
                    foreground.SetActive()
                    time.sleep(0.1)
                    
                    try:
                        edit.SetFocus()
                        time.sleep(0.05)
                    except Exception:
                        pass
                    
                    # Clear clipboard
                    subprocess.run(
                        ["powershell", "-Command", "Set-Clipboard -Value ''"],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    time.sleep(0.03)
                    
                    # Select all and copy
                    auto.SendKeys("^a")
                    time.sleep(0.1)
                    auto.SendKeys("^c")
                    time.sleep(0.1)
                    
                    # Get clipboard
                    result = subprocess.run(
                        ["powershell", "-Command", "Get-Clipboard"],
                        capture_output=True,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    clipboard = result.stdout.strip() if result.returncode == 0 else ""
                    print(f"  Clipboard result: '{clipboard}'")
                    
                    # Deselect
                    auto.SendKeys("{End}")
                    
                finally:
                    if original_window:
                        time.sleep(0.05)
                        ctypes.windll.user32.SetForegroundWindow(original_window)
            
        except Exception as e:
            print(f"  Error: {e}")
    
    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
