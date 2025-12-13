"""
Test script to detect and click "Try Again" buttons for rate limit recovery.
This will:
1. Search for "Try Again" buttons in VS Code windows
2. Wait 20 minutes (with countdown)
3. Click all "Try Again" buttons found
"""

import time
from datetime import datetime, timedelta
import ctypes
import uiautomation as auto


def get_cursor_pos():
    """Get current mouse cursor position using ctypes."""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def set_cursor_pos(x, y):
    """Set mouse cursor position instantly using ctypes."""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def get_foreground_window():
    """Get the currently active/focused window handle."""
    return ctypes.windll.user32.GetForegroundWindow()


def set_foreground_window(hwnd):
    """Set the active/focused window by handle."""
    try:
        ctypes.windll.user32.SetForegroundWindow(int(hwnd))
    except Exception:
        pass


def click_button_instantly(btn: auto.Control):
    """
    Click a button by instantly teleporting the mouse to it and back.
    Also saves and restores the active window focus.
    """
    # Save current mouse position AND active window
    original_pos = get_cursor_pos()
    original_window = get_foreground_window()
    
    try:
        # Get button's bounding rectangle
        rect = btn.BoundingRectangle
        
        # Check if button has valid coordinates
        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            # Button is off-screen or not rendered
            print(f"    Warning: Button has invalid coordinates (0,0,0,0)")
            btn.Click(simulateMove=False)
            return
        
        # Calculate center of button
        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2
        
        print(f"    Button location: ({center_x}, {center_y})")
        
        # Instantly move mouse to button center
        set_cursor_pos(center_x, center_y)
        time.sleep(0.05)  # Small delay to ensure position is set
        
        # Click the button
        btn.Click(simulateMove=False)
        print(f"    ✓ Button clicked!")
        
    finally:
        # Instantly restore mouse to original position
        time.sleep(0.05)  # Small delay after click
        set_cursor_pos(original_pos[0], original_pos[1])
        
        # Restore the original active window
        if original_window:
            time.sleep(0.05)
            set_foreground_window(original_window)


def find_all_vscode_windows(timeout: float = 0.5) -> list:
    """Find ALL VS Code windows by title suffix."""
    VSCODE_TITLE_SUFFIX = " - Visual Studio Code"
    vscode_windows = []
    
    for w in auto.GetRootControl().GetChildren():
        if isinstance(w, (auto.WindowControl, auto.PaneControl)):
            try:
                name = w.Name
                if name and name.endswith(VSCODE_TITLE_SUFFIX):
                    if w.Exists(timeout):
                        vscode_windows.append(w)
            except Exception:
                continue
    return vscode_windows


def find_try_again_buttons(vs_win: auto.Control, max_depth=50) -> list:
    """
    Recursively search for "Try Again" buttons in a VS Code window.
    Returns list of (button_control, parent_info) tuples.
    """
    found_buttons = []
    
    def search_recursive(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name
                if name and "Try Again" in name:
                    if control.Exists(0.1):
                        # Get some context about where this button is
                        parent_info = "Unknown location"
                        try:
                            parent = control.GetParentControl()
                            if parent:
                                parent_info = f"Parent: {parent.Name[:50] if parent.Name else 'No name'}"
                        except Exception:
                            pass
                        
                        found_buttons.append((control, parent_info))
            
            # Recurse into children
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
                
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found_buttons


def main():
    print("=" * 70)
    print("Try Again Button Detector and Rate Limit Recovery Tool")
    print("=" * 70)
    print()
    
    # Step 1: Find VS Code windows
    print(f"[{datetime.now()}] Searching for VS Code windows...")
    vscode_windows = find_all_vscode_windows()
    
    if not vscode_windows:
        print("  ✗ No VS Code windows found!")
        print("  Make sure VS Code is running and try again.")
        return
    
    print(f"  ✓ Found {len(vscode_windows)} VS Code window(s)")
    print()
    
    # Step 2: Search for "Try Again" buttons
    print(f"[{datetime.now()}] Searching for 'Try Again' buttons...")
    all_try_again_buttons = []
    
    for idx, vs_win in enumerate(vscode_windows, 1):
        window_title = vs_win.Name[:60] if vs_win.Name else "Unknown"
        print(f"\n  Window {idx}: '{window_title}...'")
        
        buttons = find_try_again_buttons(vs_win)
        if buttons:
            print(f"    ✓ Found {len(buttons)} 'Try Again' button(s)")
            for btn, parent_info in buttons:
                print(f"      - {parent_info}")
                all_try_again_buttons.append((vs_win, btn))
        else:
            print(f"    No 'Try Again' buttons found")
    
    print()
    print("=" * 70)
    
    if not all_try_again_buttons:
        print("No 'Try Again' buttons found in any VS Code window.")
        print("This means:")
        print("  • No rate limit is currently active, OR")
        print("  • The button may be in a different location/format")
        print()
        print("You can run this script again when you see the rate limit.")
        return
    
    print(f"\nTotal 'Try Again' buttons found: {len(all_try_again_buttons)}")
    print()
    
    # Step 3: Wait 20 minutes
    WAIT_MINUTES = 20
    wait_until = datetime.now() + timedelta(minutes=WAIT_MINUTES)
    
    print(f"[{datetime.now()}] Starting {WAIT_MINUTES}-minute wait period...")
    print(f"  Will resume at: {wait_until.strftime('%H:%M:%S')}")
    print()
    print("  Press Ctrl+C to cancel the wait")
    print()
    
    try:
        while datetime.now() < wait_until:
            remaining = (wait_until - datetime.now()).total_seconds()
            minutes = int(remaining // 60)
            seconds = int(remaining % 60)
            print(f"\r  Time remaining: {minutes:2d}:{seconds:02d}  ", end='', flush=True)
            time.sleep(1)
        print()  # New line after countdown
        
    except KeyboardInterrupt:
        print("\n\n✗ Wait cancelled by user!")
        print("  You can run this script again when ready.")
        return
    
    print()
    print(f"[{datetime.now()}] Wait period complete! Now clicking 'Try Again' buttons...")
    print()
    
    # Step 4: Click all "Try Again" buttons
    clicked_count = 0
    for vs_win, btn in all_try_again_buttons:
        try:
            window_title = vs_win.Name[:60] if vs_win.Name else "Unknown"
            print(f"  Clicking button in '{window_title}...'")
            
            # Verify button still exists
            if not btn.Exists(0.5):
                print(f"    ⚠ Button no longer exists (may have been dismissed)")
                continue
            
            click_button_instantly(btn)
            clicked_count += 1
            time.sleep(0.5)  # Small delay between clicks
            
        except Exception as e:
            print(f"    ✗ Error clicking button: {e}")
    
    print()
    print("=" * 70)
    print(f"[{datetime.now()}] Complete!")
    print(f"  Successfully clicked {clicked_count} of {len(all_try_again_buttons)} buttons")
    print()
    print("The rate limit should now be cleared.")
    print("You can resume normal Copilot usage.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nScript interrupted by user.")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()

