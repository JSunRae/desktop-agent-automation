"""
Send a confirmation request to the finished panel
"""
import uiautomation as auto
import time
import pyperclip

def main():
    print("Looking for finished panel to send message...")
    time.sleep(1)  # Small delay
    
    # Get all VS Code windows
    windows = []
    for win in auto.GetRootControl().GetChildren():
        if win.ControlType == auto.ControlType.WindowControl:
            name = win.Name or ''
            if 'Visual Studio Code' in name:
                windows.append(win)
    
    print(f"Found {len(windows)} VS Code windows")
    
    finished_window = None
    send_btn_found = None
    
    for win in windows:
        title = win.Name[:60]
        
        # Check if running (Cancel visible)
        is_running = False
        try:
            cancel_btn = win.ButtonControl(searchDepth=15, Name='Cancel')
            if cancel_btn.Exists(maxSearchSeconds=0.5):
                rect = cancel_btn.BoundingRectangle
                is_running = rect.width() > 0 and rect.height() > 0
        except Exception:
            pass
        
        # Check if finished (Send visible)
        has_send = False
        send_btn = None
        try:
            send_btn = win.ButtonControl(searchDepth=15, Name='Send')
            if send_btn.Exists(maxSearchSeconds=0.5):
                rect = send_btn.BoundingRectangle
                has_send = rect.width() > 0 and rect.height() > 0
        except Exception:
            pass
        
        print(f"  {title}: Running={is_running}, HasSend={has_send}")
        
        if has_send and not is_running:
            finished_window = win
            send_btn_found = send_btn
            print(f"  -> SELECTED as finished panel")
    
    if not finished_window:
        print("\nNo finished panel found!")
        return
    
    print("\n" + "=" * 60)
    print("SENDING MESSAGE TO FINISHED PANEL")
    print("=" * 60)
    
    message = 'If you are finished, confirm with "finished".'
    print(f"Message: {message}")
    
    # Focus the window
    finished_window.SetFocus()
    time.sleep(0.4)
    
    # Focus chat input with Ctrl+L
    print("Focusing chat input...")
    auto.SendKeys('{Ctrl}l', interval=0.05)
    time.sleep(0.3)
    
    # Clear any existing text and paste message
    print("Pasting message...")
    pyperclip.copy(message)
    auto.SendKeys('{Ctrl}a', interval=0.05)
    time.sleep(0.1)
    auto.SendKeys('{Ctrl}v', interval=0.05)
    time.sleep(0.3)
    
    # Click Send button
    print("Clicking Send...")
    try:
        if send_btn_found:
            send_btn_found.Click()
            print("\n✓ Message sent successfully!")
        else:
            # Use keyboard shortcut
            auto.SendKeys('{Ctrl}{Enter}', interval=0.05)
            print("\n✓ Message sent via Ctrl+Enter!")
    except Exception as e:
        print(f"\n✗ Error clicking send: {e}")
        # Try keyboard shortcut as fallback
        try:
            auto.SendKeys('{Ctrl}{Enter}', interval=0.05)
            print("  Fallback: Sent via Ctrl+Enter")
        except Exception:
            pass

if __name__ == "__main__":
    main()
