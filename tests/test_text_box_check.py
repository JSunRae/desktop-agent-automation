"""
Test script to check if the chat input box has text in it.
"""
import time
import uiautomation as auto
import sys
sys.path.insert(0, '.')

from automation.panel_tracker import (
    find_chat_input_box,
    get_chat_input_text,
    send_text_to_chat,
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
    print("=" * 60)
    print("Testing Chat Input Box Text Detection")
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
        
        # Test get_chat_input_text function
        print("Checking for existing text in chat input box...")
        existing_text = get_chat_input_text(win)
        
        if existing_text is None:
            print("  ❌ Could not access chat input box")
        elif existing_text:
            print(f"  ✓ Found existing text: '{existing_text[:100]}'")
            print(f"  Length: {len(existing_text)} chars")
        else:
            print("  ✓ Chat input box is empty")
        
        # Test send_text_to_chat - should NOT send if there's text
        print("\nTesting send_text_to_chat (should skip if text present)...")
        test_message = "TEST MESSAGE - This should NOT be sent if text exists"
        result = send_text_to_chat(win, test_message)
        
        if result:
            print("  ⚠ WARNING: Text was sent (input was empty)")
        else:
            print("  ✓ Correctly skipped sending (input had text)")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
