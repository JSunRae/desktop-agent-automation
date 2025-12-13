"""
Test to find text in chat input using ExpandToEnclosingUnit.
NO keystrokes, NO clipboard.
"""
import uiautomation as auto
import ctypes
from typing import List

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


def get_all_text_via_expand(editor) -> str:
    """
    Get text by expanding the document range.
    """
    try:
        text_pattern = editor.GetTextPattern()
        if not text_pattern:
            return ""
        
        doc_range = text_pattern.DocumentRange
        if not doc_range:
            return ""
        
        # Clone and expand to document level
        try:
            cloned = doc_range.Clone()
            # TextUnit values: 0=Character, 1=Format, 2=Word, 3=Line, 4=Paragraph, 5=Page, 6=Document
            cloned.ExpandToEnclosingUnit(6)  # 6 = Document
            text = cloned.GetText(-1)
            if text:
                return text
        except Exception:
            pass
        
        # Try expanding to Line
        try:
            cloned = doc_range.Clone()
            cloned.ExpandToEnclosingUnit(3)  # 3 = Line
            text = cloned.GetText(-1)
            if text:
                return text
        except Exception:
            pass
        
        # Try just getting text with a large limit
        try:
            text = doc_range.GetText(10000)
            if text:
                return text
        except Exception:
            pass
        
        return ""
        
    except Exception as e:
        print(f"  Error: {e}")
        return ""


def main():
    print("=" * 70)
    print("Reading Chat Input Text via ExpandToEnclosingUnit")
    print("=" * 70)
    
    windows = find_all_vscode_windows()
    print(f"\nFound {len(windows)} VS Code window(s)\n")
    
    # Get foreground window handle
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    for w in windows[:5]:  # Check up to 5 windows
        try:
            is_foreground = w.NativeWindowHandle == hwnd
        except Exception:
            is_foreground = False
        
        title = w.Name or "Unknown"
        fg_marker = " [FOREGROUND]" if is_foreground else ""
        print(f"\nWindow: {title[:55]}...{fg_marker}")
        print("-" * 60)
        
        editors = find_chat_editors(w)
        if not editors:
            print("  No chat editor found")
            continue
        
        for i, editor in enumerate(editors, 1):
            rect = editor.BoundingRectangle
            # Filter out editors that are not visible (zero bounds or off-screen)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if rect.left < -5000 or rect.top < -5000:
                continue
                
            print(f"\n  [Chat Input {i}] at ({rect.left}, {rect.top})")
            
            text = get_all_text_via_expand(editor)
            
            if text:
                # Clean up the text for display
                display_text = text.strip()
                # Replace special unicode chars
                display_text = display_text.encode('ascii', 'replace').decode('ascii')
                print(f"  TEXT FOUND: '{display_text[:100]}'")
                print(f"  Length: {len(text)} chars")
            else:
                print("  (empty - no text in input)")
    
    print("\n" + "=" * 70)
    print("Done - no keystrokes sent!")
    print("=" * 70)


if __name__ == "__main__":
    main()
