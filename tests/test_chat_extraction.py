"""
Test script to extract chat window text from VS Code Copilot panels.
This script finds all VS Code windows and attempts to extract the latest
chat messages and confirmation dialogs without clicking anything.
"""
from datetime import datetime

import uiautomation as auto


VSCODE_TITLE_SUFFIX = " - Visual Studio Code"


def find_all_vscode_windows(timeout: float = 0.5) -> list:
    """
    Find ALL VS Code windows by title suffix.
    Returns a list of Controls (WindowControl or PaneControl).
    """
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


def extract_chat_dialog_info(control, depth=0, max_depth=50, found_dialogs=None):
    """
    Recursively search for Chat Confirmation Dialog elements and extract their info.
    """
    if found_dialogs is None:
        found_dialogs = []
    
    if depth > max_depth:
        return found_dialogs
    
    try:
        name = control.Name
        control_type = control.ControlTypeName
        
        # Look for Chat Confirmation Dialog groups
        if name and "Chat Confirmation Dialog" in name:
            dialog_info = {
                'type': 'confirmation_dialog',
                'name': name,
                'control_type': control_type,
                'full_text': name.replace("Chat Confirmation Dialog", "").strip()
            }
            found_dialogs.append(dialog_info)
            print(f"\n{'  ' * depth}[DIALOG] {name[:100]}")
        
        # Look for chat confirmation required text
        elif name and "Chat confirmation required:" in name:
            dialog_info = {
                'type': 'confirmation_text',
                'name': name,
                'control_type': control_type,
                'full_text': name
            }
            found_dialogs.append(dialog_info)
            print(f"\n{'  ' * depth}[CONFIRMATION] {name[:150]}")
        
        # Look for Allow buttons and their context
        elif name == "Allow (Ctrl+Enter)" and isinstance(control, auto.ButtonControl):
            # Try to get parent context
            parent_text = "Unknown"
            try:
                parent = control.GetParentControl()
                if parent and parent.Name:
                    parent_text = parent.Name[:100]
            except Exception:
                pass
            
            dialog_info = {
                'type': 'allow_button',
                'name': name,
                'control_type': control_type,
                'parent_context': parent_text
            }
            found_dialogs.append(dialog_info)
            print(f"\n{'  ' * depth}[ALLOW BUTTON] Parent: {parent_text}")
        
        # Look for Keep All Edits buttons
        elif name == "Keep All Edits (Ctrl+Enter)" and isinstance(control, auto.ButtonControl):
            # Try to get parent context
            parent_text = "Unknown"
            try:
                parent = control.GetParentControl()
                if parent and parent.Name:
                    parent_text = parent.Name[:100]
            except Exception:
                pass
            
            dialog_info = {
                'type': 'keep_edits_button',
                'name': name,
                'control_type': control_type,
                'parent_context': parent_text
            }
            found_dialogs.append(dialog_info)
            print(f"\n{'  ' * depth}[KEEP ALL EDITS BUTTON] Parent: {parent_text}")
        
        # Look for Chat list controls
        elif name == "Chat" and control_type == "ListControl":
            print(f"\n{'  ' * depth}[CHAT LIST FOUND]")
            # Try to get recent chat items
            try:
                children = control.GetChildren()
                print(f"{'  ' * depth}  Chat list has {len(children)} children")
                
                # Get the last chat item (most recent message)
                if children:
                    last_item = children[-1]
                    try:
                        item_name = last_item.Name
                        if item_name:
                            print(f"\n{'  ' * depth}  [LAST CHAT MESSAGE]")
                            # Try to find the last line (which should be the question)
                            lines = item_name.split('\n')
                            if lines:
                                last_line = lines[-1].strip()
                                print(f"{'  ' * depth}  Last line: {last_line}")
                            
                            # Show full message (truncated)
                            print(f"\n{'  ' * depth}  Full message preview (first 500 chars):")
                            print(f"{'  ' * depth}  {item_name[:500]}")
                            
                            if len(item_name) > 500:
                                print(f"{'  ' * depth}  ... (message continues, total length: {len(item_name)} chars)")
                            
                            # Store the chat message info
                            dialog_info = {
                                'type': 'chat_message',
                                'full_text': item_name,
                                'last_line': lines[-1].strip() if lines else '',
                                'control_type': last_item.ControlTypeName
                            }
                            found_dialogs.append(dialog_info)
                    except Exception as e:
                        print(f"{'  ' * depth}  Error reading last item: {e}")
                
                # Also check for list items that might contain questions
                print(f"\n{'  ' * depth}  Scanning all list items for questions...")
                for i, child in enumerate(children):
                    try:
                        if isinstance(child, auto.ListItemControl):
                            item_name = child.Name
                            if item_name and '?' in item_name:
                                # This item contains a question mark, likely important
                                lines = item_name.split('\n')
                                question_lines = [line for line in lines if '?' in line]
                                if question_lines:
                                    print(f"{'  ' * depth}  Item {i} question: {question_lines[-1][:100]}")
                    except Exception:
                        pass
                        
            except Exception as e:
                print(f"{'  ' * depth}  Error reading chat list: {e}")
        
        # Recurse into children
        for child in control.GetChildren():
            extract_chat_dialog_info(child, depth + 1, max_depth, found_dialogs)
    
    except Exception:
        # Silently skip controls that error out
        pass
    
    return found_dialogs


def main():
    print("=" * 80)
    print("VS Code Chat Window Text Extraction Test")
    print("=" * 80)
    print(f"Time: {datetime.now()}\n")
    
    vscode_windows = find_all_vscode_windows()
    
    if not vscode_windows:
        print("❌ No VS Code windows found!")
        return
    
    print(f"✓ Found {len(vscode_windows)} VS Code window(s)\n")
    
    for idx, vs_win in enumerate(vscode_windows, 1):
        print("\n" + "=" * 80)
        print(f"WINDOW {idx}: {vs_win.Name}")
        print("=" * 80)
        
        try:
            # Extract chat dialogs and info
            dialogs = extract_chat_dialog_info(vs_win, max_depth=50)
            
            print(f"\n\nSummary for Window {idx}:")
            print("-" * 80)
            
            if dialogs:
                confirmation_dialogs = [d for d in dialogs if d['type'] == 'confirmation_dialog']
                confirmation_texts = [d for d in dialogs if d['type'] == 'confirmation_text']
                allow_buttons = [d for d in dialogs if d['type'] == 'allow_button']
                keep_edits_buttons = [d for d in dialogs if d['type'] == 'keep_edits_button']
                chat_messages = [d for d in dialogs if d['type'] == 'chat_message']
                
                if chat_messages:
                    print(f"  Chat Messages: {len(chat_messages)}")
                    for msg in chat_messages:
                        print("\n    Last line of message:")
                        print(f"    >>> {msg['last_line']}")
                
                if confirmation_dialogs:
                    print(f"\n  Confirmation Dialogs: {len(confirmation_dialogs)}")
                    for dialog in confirmation_dialogs:
                        print(f"    • {dialog['full_text'][:100]}")
                
                if confirmation_texts:
                    print(f"\n  Confirmation Texts: {len(confirmation_texts)}")
                    for text in confirmation_texts:
                        print(f"    • {text['full_text'][:150]}")
                
                if allow_buttons:
                    print(f"\n  Allow Buttons: {len(allow_buttons)}")
                    for btn in allow_buttons:
                        print(f"    • Parent: {btn['parent_context']}")
                
                if keep_edits_buttons:
                    print(f"\n  Keep All Edits Buttons: {len(keep_edits_buttons)}")
                    for btn in keep_edits_buttons:
                        print(f"    • Parent: {btn['parent_context']}")
                
                if not any([chat_messages, confirmation_dialogs, confirmation_texts, allow_buttons, keep_edits_buttons]):
                    print("  No relevant content found.")
            else:
                print("  No chat dialogs or confirmations found in this window.")
        
        except Exception as e:
            print(f"❌ Error processing window: {e}")
    
    print("\n" + "=" * 80)
    print("Test Complete")
    print("=" * 80)


if __name__ == "__main__":
    main()
