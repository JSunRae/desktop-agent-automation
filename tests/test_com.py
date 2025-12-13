"""
Test to check document range bounding rectangle.
If text exists, the document range might have different bounds.
"""
import uiautomation as auto
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


def find_chat_editors(vs_win, max_depth=60):
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


def try_raw_com_approach(editor):
    """Try accessing COM interface directly for text pattern."""
    results = {}
    try:
        # Get the element
        element = editor.Element
        if element:
            results['has_element'] = True
            
            # Try to get patterns via COM
            try:
                # IUIAutomationTextPattern = pattern ID 10014
                TEXT_PATTERN_ID = 10014
                pattern = element.GetCurrentPattern(TEXT_PATTERN_ID)
                if pattern:
                    results['has_text_pattern_com'] = True
                    
                    # Try to get SupportedTextSelection
                    try:
                        supported = pattern.SupportedTextSelection
                        results['supported_text_selection'] = supported
                    except Exception as e:
                        results['selection_error'] = str(e)[:50]
                    
                    # Get document range
                    try:
                        doc_range = pattern.DocumentRange
                        if doc_range:
                            # Try GetText with different lengths
                            for length in [-1, 1, 10, 100, 1000]:
                                try:
                                    text = doc_range.GetText(length)
                                    if text:
                                        results[f'text_{length}'] = repr(text)[:50]
                                    else:
                                        results[f'text_{length}'] = "(empty)"
                                except Exception as e:
                                    results[f'text_{length}_err'] = str(e)[:30]
                                    
                            # Try to get bounding rectangles
                            try:
                                rects = doc_range.GetBoundingRectangles()
                                if rects:
                                    results['rects_count'] = len(rects)
                                    results['rects_sample'] = list(rects)[:8]  # First 2 rects (4 values each)
                                else:
                                    results['rects'] = "(none)"
                            except Exception as e:
                                results['rects_err'] = str(e)[:40]
                                
                    except Exception as e:
                        results['doc_range_error'] = str(e)[:50]
                else:
                    results['has_text_pattern_com'] = False
            except Exception as e:
                results['pattern_error'] = str(e)[:50]
        else:
            results['has_element'] = False
    except Exception as e:
        results['error'] = str(e)[:50]
    
    return results


def check_text_pattern_wrapper(editor):
    """Check TextPattern through the wrapper library."""
    results = {}
    
    try:
        tp = editor.GetTextPattern()
        if tp:
            results['wrapper_available'] = True
            
            # Get document range text
            try:
                doc_range = tp.DocumentRange
                text = doc_range.GetText(-1)
                results['doc_text'] = repr(text)[:60] if text else "(empty)"
                
                # Try GetBoundingRectangles 
                try:
                    rects = doc_range.GetBoundingRectangles()
                    if rects:
                        results['wrapper_rects'] = list(rects)[:8]
                except Exception as e:
                    results['wrapper_rects_err'] = str(e)[:40]
                    
            except Exception as e:
                results['doc_range_err'] = str(e)[:40]
        else:
            results['wrapper_available'] = False
    except Exception as e:
        results['wrapper_err'] = str(e)[:40]
    
    return results


def main():
    print("=" * 70)
    print("COM TextPattern Analysis")
    print("=" * 70)
    print()
    
    windows = find_all_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s)")
    
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    for w in windows[:2]:
        try:
            is_foreground = w.NativeWindowHandle == hwnd
        except Exception:
            is_foreground = False
        
        title = w.Name or "Unknown"
        fg_marker = " [FOREGROUND]" if is_foreground else ""
        print(f"\nWindow: {title[:50]}...{fg_marker}")
        print("-" * 60)
        
        editors = find_chat_editors(w)
        print(f"Found {len(editors)} chat editor(s)")
        
        for i, editor in enumerate(editors, 1):
            rect = editor.BoundingRectangle
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if rect.left < -5000 or rect.top < -5000:
                continue
            
            print(f"\n  [Chat Input {i}] at ({rect.left}, {rect.top}), {rect.width()}x{rect.height()}")
            
            # Check HasKeyboardFocus
            try:
                has_focus = editor.HasKeyboardFocus
                print(f"    HasKeyboardFocus: {has_focus}")
            except Exception:
                pass
            
            # Wrapper TextPattern check  
            wrapper_results = check_text_pattern_wrapper(editor)
            print(f"    Wrapper results: {wrapper_results}")
            
            # Raw COM approach
            com_results = try_raw_com_approach(editor)
            print(f"    COM results: {com_results}")
    
    print("\n" + "=" * 70)
    print("Analysis complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
