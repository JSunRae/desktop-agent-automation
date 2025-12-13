"""
Test: Check last output of finished panel and send a message to it
"""
import uiautomation as auto
import time
import re

def get_current_desktop_vscode_windows():
    """Get all VS Code windows on the current desktop"""
    windows = []
    for win in auto.GetRootControl().GetChildren():
        if win.ControlType == auto.ControlType.WindowControl:
            name = win.Name or ""
            if "Visual Studio Code" in name:
                windows.append(win)
    return windows

def find_chat_panel(window):
    """Find the chat panel in a VS Code window"""
    try:
        # Look for the Copilot chat panel
        chat_panel = window.DocumentControl(searchDepth=15, Name="Copilot Chat")
        if chat_panel.Exists(maxSearchSeconds=1):
            return chat_panel
    except:
        pass
    return None

def get_chat_output_text(window, max_chars=2000):
    """Get the chat output/response text from the panel"""
    try:
        # Find all text/document controls that might contain chat output
        chat_panel = find_chat_panel(window)
        if not chat_panel:
            return None
            
        # Look for the chat response area - typically a group or document
        # that contains the AI responses
        texts = []
        
        # Try to find groups with response content
        for group in chat_panel.GetChildren():
            try:
                name = group.Name or ""
                # Get text content
                if hasattr(group, 'GetChildren'):
                    for child in group.GetChildren():
                        text = child.Name or ""
                        if text and len(text) > 5:
                            texts.append(text)
            except:
                continue
        
        # Also try finding text elements directly
        try:
            for elem in chat_panel.GetChildren():
                if elem.ControlType == auto.ControlType.TextControl:
                    text = elem.Name or ""
                    if text and len(text) > 5:
                        texts.append(text)
        except:
            pass
            
        if texts:
            combined = "\n".join(texts)
            return combined[-max_chars:] if len(combined) > max_chars else combined
            
    except Exception as e:
        return f"Error: {e}"
    return None

def get_full_chat_content_via_selection(window):
    """Try to get chat content by selecting all and copying from the chat area"""
    import pyperclip
    
    try:
        chat_panel = find_chat_panel(window)
        if not chat_panel:
            return None
            
        # Save current clipboard
        original_clipboard = ""
        try:
            original_clipboard = pyperclip.paste()
        except:
            pass
            
        # Set a marker
        marker = f"__CHAT_MARKER_{time.time()}__"
        pyperclip.copy(marker)
        
        # Focus on the chat panel's output area
        # First find a group or document in the chat panel
        target = chat_panel
        try:
            for child in chat_panel.GetChildren():
                if child.ControlType in [auto.ControlType.GroupControl, auto.ControlType.DocumentControl]:
                    target = child
                    break
        except:
            pass
            
        target.SetFocus()
        time.sleep(0.1)
        
        # Try Ctrl+A, Ctrl+C
        auto.SendKeys('{Ctrl}a', interval=0.05)
        time.sleep(0.1)
        auto.SendKeys('{Ctrl}c', interval=0.05)
        time.sleep(0.1)
        
        # Get clipboard content
        content = ""
        try:
            content = pyperclip.paste()
        except:
            pass
            
        # Restore clipboard
        try:
            pyperclip.copy(original_clipboard)
        except:
            pass
            
        if content and content != marker:
            return content
            
    except Exception as e:
        return f"Error: {e}"
    return None

def is_panel_running(window):
    """Check if the panel has Cancel button visible (running)"""
    try:
        cancel_btn = window.ButtonControl(searchDepth=15, Name="Cancel")
        if cancel_btn.Exists(maxSearchSeconds=0.5):
            rect = cancel_btn.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                return True
    except:
        pass
    return False

def find_send_button(window):
    """Find the Send button in the window"""
    try:
        send_btn = window.ButtonControl(searchDepth=15, Name="Send")
        if send_btn.Exists(maxSearchSeconds=0.5):
            rect = send_btn.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                return send_btn
    except:
        pass
    return None

def find_chat_input(window):
    """Find the chat input text box"""
    try:
        # Look for the chat editor/input
        editor = window.EditControl(searchDepth=15, AutomationId="")
        
        # Try multiple approaches
        for edit in window.GetChildren():
            try:
                edits = edit.GetChildren() if hasattr(edit, 'GetChildren') else []
                for e in edits:
                    if e.ControlType == auto.ControlType.EditControl:
                        return e
            except:
                continue
                
        # Direct search for edit controls
        edits = window.FindAll(auto.TreeScope.Descendants, auto.PropertyCondition(auto.PropertyId.ControlType, auto.ControlType.EditControl))
        if edits:
            for e in edits:
                try:
                    name = e.Name or ""
                    if "chat" in name.lower() or "copilot" in name.lower() or "ask" in name.lower():
                        return e
                except:
                    continue
            # Return first edit if none matched
            return edits[0] if edits else None
    except:
        pass
    return None

def send_message_to_panel(window, message):
    """Send a message to the chat panel"""
    try:
        # Focus the window
        window.SetFocus()
        time.sleep(0.3)
        
        # Find send button first to confirm panel is ready
        send_btn = find_send_button(window)
        if not send_btn:
            return False, "No Send button found - panel may be running"
            
        # Try to find and click on the chat input area
        # Use keyboard shortcut to focus chat input: Ctrl+L is common for VS Code Copilot chat
        auto.SendKeys('{Ctrl}l', interval=0.05)
        time.sleep(0.2)
        
        # Type the message
        # First clear any existing text
        auto.SendKeys('{Ctrl}a', interval=0.05)
        time.sleep(0.1)
        
        # Type the message using SendKeys with special handling
        # For complex messages, use clipboard
        import pyperclip
        pyperclip.copy(message)
        auto.SendKeys('{Ctrl}v', interval=0.05)
        time.sleep(0.2)
        
        # Click Send or use Ctrl+Enter
        send_btn.Click()
        
        return True, "Message sent successfully"
        
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("=" * 70)
    print(f"Check Output and Send Test - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    windows = get_current_desktop_vscode_windows()
    print(f"\n📋 Found {len(windows)} VS Code window(s)")
    
    finished_window = None
    running_window = None
    
    for i, win in enumerate(windows, 1):
        title = win.Name[:60] + "..." if len(win.Name) > 60 else win.Name
        running = is_panel_running(win)
        
        print(f"\n{'─' * 70}")
        print(f"Window {i}: {title}")
        print(f"{'─' * 70}")
        print(f"  Status: {'RUNNING' if running else 'FINISHED/IDLE'}")
        
        if running:
            running_window = win
        else:
            finished_window = win
            
            # Get the last output from the finished panel
            print(f"\n  📄 Attempting to get last output content...")
            
            # Try the simple method first
            output = get_chat_output_text(win, max_chars=1500)
            if output:
                print(f"\n  Last Output (via text controls):")
                print(f"  {'-' * 60}")
                # Show last part of output
                lines = output.split('\n')[-20:]  # Last 20 lines
                for line in lines:
                    print(f"    {line[:100]}")
            else:
                print(f"  (Could not get output via text controls)")
                
            # Check for "next steps" patterns
            if output:
                next_step_patterns = [
                    r'next\s*step',
                    r'would you like',
                    r'shall i',
                    r'let me know',
                    r'continue with',
                    r'proceed',
                    r'ready to',
                    r'waiting for',
                    r'\?\s*$',  # ends with question
                ]
                has_next_steps = any(re.search(p, output.lower()) for p in next_step_patterns)
                print(f"\n  Has next step indicators: {has_next_steps}")
    
    if finished_window:
        print(f"\n{'=' * 70}")
        print("SENDING MESSAGE TO FINISHED PANEL")
        print("=" * 70)
        
        message = 'If you are finished, confirm with "finished".'
        print(f"\n  Message: {message}")
        print(f"\n  Attempting to send...")
        
        success, result = send_message_to_panel(finished_window, message)
        
        if success:
            print(f"  ✓ {result}")
        else:
            print(f"  ✗ {result}")
    else:
        print("\n⚠ No finished panel found to send message to")
        
    print(f"\n{'=' * 70}")
    print("TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    main()
