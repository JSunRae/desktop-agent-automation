"""
Verify the text detection method is working correctly.
Tests both empty and non-empty input boxes.
"""

from automation.panel_tracker import (
    find_chat_editor_control,
    _check_editor_has_text_via_clipboard,
    _set_clipboard_text,
    _get_clipboard_text,
)
import uiautomation as auto
import time
import ctypes

def find_vscode_windows():
    """Find all VS Code windows."""
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
    return windows


def test_text_detection():
    """Test the text detection in chat input boxes."""
    print("=" * 70)
    print("Text Detection Verification Test")
    print("=" * 70)
    
    windows = find_vscode_windows()
    print(f"\nFound {len(windows)} VS Code windows")
    
    original_window = ctypes.windll.user32.GetForegroundWindow()
    
    for i, w in enumerate(windows, 1):
        title = w.Name[:60] if w.Name else "Unknown"
        print(f"\n{'─' * 70}")
        print(f"Window {i}: {title}...")
        print("─" * 70)
        
        # Find the editor
        editor = find_chat_editor_control(w)
        if not editor:
            print("  ❌ No chat editor found")
            continue
        
        print("  ✓ Found chat editor control")
        
        try:
            # Step 1: Set a known marker on clipboard
            marker = "__TEST_EMPTY_MARKER__"
            _set_clipboard_text(marker)
            time.sleep(0.05)
            
            # Verify marker was set
            clip_before = _get_clipboard_text()
            print(f"  Clipboard before: '{clip_before[:50]}...'")
            
            # Step 2: Activate window and focus editor
            w.SetActive()
            time.sleep(0.2)
            
            editor.SetFocus()
            time.sleep(0.15)
            
            # Step 3: Use the detection function
            has_text, detected_text = _check_editor_has_text_via_clipboard(editor)
            
            # Step 4: Check what happened
            clip_after = _get_clipboard_text()
            
            print(f"\n  Results:")
            print(f"    Has text: {has_text}")
            if has_text:
                preview = detected_text[:80].replace('\n', '\\n')
                print(f"    Detected text: '{preview}...'")
            else:
                print(f"    Detected text: (empty)")
            
            print(f"\n  Clipboard after: '{clip_after[:50]}...'")
            
            if clip_after == marker:
                print("  ✓ Clipboard unchanged (marker present) - empty editor")
            elif has_text:
                print("  ✓ Clipboard changed - editor had text")
            else:
                print("  ⚠ Unexpected state - clipboard changed but no text detected")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        finally:
            # Restore original window
            if original_window:
                time.sleep(0.1)
                ctypes.windll.user32.SetForegroundWindow(original_window)
    
    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)


if __name__ == "__main__":
    test_text_detection()
