"""
Test script to check if the chat input box has text.
Uses only UI Automation patterns - NO clipboard, NO SendKeys.
"""
import uiautomation as auto
import ctypes
import time
from typing import List

VSCODE_TITLE_SUFFIX = " - Visual Studio Code"


def find_all_vscode_windows():
    """Find all VS Code windows on current desktop."""
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


def find_chat_editors(vs_win, max_depth=60) -> List[auto.Control]:
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


def get_text_length_from_text_pattern(editor) -> int:
    """
    Try to get the text LENGTH from TextPattern without using clipboard.
    Returns -1 if cannot determine.
    """
    try:
        # Get TextPattern
        text_pattern = editor.GetTextPattern()
        if not text_pattern:
            return -1
        
        doc_range = text_pattern.DocumentRange
        if not doc_range:
            return -1
        
        # Get the text - this might return empty even when there's text
        text = doc_range.GetText(-1)
        if text:
            return len(text)
        
        # Try to check if the range has any content by getting bounding rectangles
        # If there's text, there should be bounding rectangles
        try:
            rects = doc_range.GetBoundingRectangles()
            if rects and len(rects) > 0:
                # There are bounding rectangles, meaning there's visible content
                return 1  # At least some text
        except Exception:
            pass
        
        return 0
        
    except Exception as e:
        print(f"    Error in TextPattern: {e}")
        return -1


def check_if_text_via_text_pattern2(editor) -> dict:
    """
    Try various TextPattern2 methods to detect if there's text.
    """
    results = {}
    
    # TextPattern methods
    try:
        text_pattern = editor.GetTextPattern()
        if text_pattern:
            doc_range = text_pattern.DocumentRange
            if doc_range:
                # GetText
                text = doc_range.GetText(-1)
                results['GetText(-1)'] = repr(text) if text else "(empty)"
                
                # GetText with limit
                text_limited = doc_range.GetText(1000)
                results['GetText(1000)'] = repr(text_limited) if text_limited else "(empty)"
                
                # Try to get enclosing element
                try:
                    enclosing = doc_range.GetEnclosingElement()
                    if enclosing:
                        results['EnclosingElement.Name'] = enclosing.Name[:50] if enclosing.Name else "(none)"
                except Exception as e:
                    results['EnclosingElement'] = f"error: {e}"
                
                # Try ExpandToEnclosingUnit
                try:
                    # Clone the range first
                    cloned = doc_range.Clone()
                    cloned.ExpandToEnclosingUnit(1)  # 1 = Character
                    char_text = cloned.GetText(10)
                    results['FirstChars'] = repr(char_text) if char_text else "(empty)"
                except Exception as e:
                    results['ExpandToChar'] = f"error: {e}"
                    
    except Exception as e:
        results['TextPattern'] = f"error: {e}"
    
    # Try getting caret position - if there's a caret at position > 0, there's likely text before it
    try:
        text_pattern = editor.GetTextPattern()
        if text_pattern:
            try:
                # GetCaretRange might indicate position
                caret_range = text_pattern.GetCaretRange()
                if caret_range:
                    results['CaretRange'] = "exists"
            except Exception:
                pass
    except Exception:
        pass
    
    return results


def check_control_descendants(editor) -> str:
    """Check if the edit control has any child elements that might contain text."""
    try:
        children = editor.GetChildren()
        if children:
            return f"{len(children)} children"
        return "no children"
    except Exception as e:
        return f"error: {e}"


def main():
    print("=" * 70)
    print("Testing Chat Input Box - NO CLIPBOARD/SENDKEYS")
    print("=" * 70)
    print("\nThis test will NOT send any keystrokes or use clipboard.")
    print("It only reads UI Automation properties.\n")
    
    # Find the foreground VS Code window
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    target_win = None
    
    windows = find_all_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s) total.\n")
    
    # Find the one that matches foreground or just use first one on this desktop
    for w in windows:
        try:
            if w.NativeWindowHandle == hwnd:
                target_win = w
                print(f"Using foreground window: {w.Name[:60]}...")
                break
        except Exception:
            continue
    
    if not target_win and windows:
        # Just check the first few windows
        for w in windows[:3]:
            title = w.Name or "Unknown"
            print(f"\nChecking: {title[:60]}...")
            
            editors = find_chat_editors(w)
            if editors:
                print(f"  Found {len(editors)} chat editor(s)")
                
                for i, editor in enumerate(editors, 1):
                    rect = editor.BoundingRectangle
                    print(f"\n  [Editor {i}] Bounds: {rect}")
                    
                    # Check text pattern results
                    print("  TextPattern analysis:")
                    tp_results = check_if_text_via_text_pattern2(editor)
                    for key, val in tp_results.items():
                        print(f"    {key}: {val}")
                    
                    # Check children
                    children_info = check_control_descendants(editor)
                    print(f"  Children: {children_info}")
                    
                    # Text length check
                    text_len = get_text_length_from_text_pattern(editor)
                    print(f"  Detected text length: {text_len}")
            else:
                print("  No chat editor found")
    
    elif target_win:
        editors = find_chat_editors(target_win)
        print(f"\nFound {len(editors)} chat editor(s) in foreground window")
        
        for i, editor in enumerate(editors, 1):
            rect = editor.BoundingRectangle
            print(f"\n[Editor {i}] Bounds: {rect}")
            
            # Check text pattern results
            print("TextPattern analysis:")
            tp_results = check_if_text_via_text_pattern2(editor)
            for key, val in tp_results.items():
                print(f"  {key}: {val}")
            
            # Check children
            children_info = check_control_descendants(editor)
            print(f"Children: {children_info}")
            
            # Text length check
            text_len = get_text_length_from_text_pattern(editor)
            print(f"Detected text length: {text_len}")
    
    print("\n" + "=" * 70)
    print("Test complete - no keystrokes were sent!")
    print("=" * 70)


if __name__ == "__main__":
    main()
