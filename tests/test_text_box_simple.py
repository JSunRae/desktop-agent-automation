"""
Simple test script to check if the chat input box has text in it.
Non-interactive version that just reports what it finds.
"""
import uiautomation as auto
import subprocess
import ctypes

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


def check_input_text(vs_win):
    """Check what text is in the chat input box."""
    import time
    
    try:
        original_window = ctypes.windll.user32.GetForegroundWindow()
        
        try:
            # Activate the VS Code window
            vs_win.SetActive()
            time.sleep(0.15)
            
            # Clear clipboard first
            subprocess.run(
                ["powershell", "-Command", "Set-Clipboard -Value ''"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            time.sleep(0.05)
            
            # Select all and copy in the input box
            auto.SendKeys("^a")  # Ctrl+A to select all
            time.sleep(0.08)
            auto.SendKeys("^c")  # Ctrl+C to copy
            time.sleep(0.08)
            
            # Get clipboard content
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # Deselect by pressing End
            auto.SendKeys("{End}")
            time.sleep(0.02)
            
            clipboard_text = result.stdout.strip() if result.returncode == 0 else ""
            return clipboard_text
            
        finally:
            # Restore original window
            if original_window:
                time.sleep(0.05)
                ctypes.windll.user32.SetForegroundWindow(original_window)
                
    except Exception as e:
        return f"ERROR: {e}"


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
        
        print("Checking for existing text in chat input box...")
        existing_text = check_input_text(win)
        
        if existing_text.startswith("ERROR:"):
            print(f"  ❌ {existing_text}")
        elif existing_text:
            print(f"  ✓ Found existing text!")
            print(f"    Content: '{existing_text[:100]}'")
            print(f"    Length: {len(existing_text)} chars")
            print("  → send_text_to_chat() would SKIP sending")
        else:
            print("  ✓ Chat input box is empty")
            print("  → send_text_to_chat() would send the message")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
