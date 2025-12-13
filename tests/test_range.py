"""
Test to detect text in chat input by checking visible text range.
NO keystrokes, NO clipboard.
"""
import uiautomation as auto
import ctypes
from typing import List, Tuple

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


def analyze_text_range(editor) -> dict:
    """
    Analyze the text range of an editor to detect if there's user text.
    """
    results = {}
    
    try:
        text_pattern = editor.GetTextPattern()
        if not text_pattern:
            return {"error": "no TextPattern"}
        
        doc_range = text_pattern.DocumentRange
        if not doc_range:
            return {"error": "no DocumentRange"}
        
        # Get visible ranges - this might give us just the visible/typed text
        try:
            visible_ranges = text_pattern.GetVisibleRanges()
            if visible_ranges:
                results['visible_range_count'] = len(visible_ranges)
                if len(visible_ranges) > 0:
                    first_visible = visible_ranges[0]
                    visible_text = first_visible.GetText(500)
                    results['first_visible_text'] = repr(visible_text[:200]) if visible_text else "(empty)"
        except Exception as e:
            results['visible_ranges'] = f"error: {e}"
        
        # Try GetSelection - selected text
        try:
            selections = text_pattern.GetSelection()
            if selections and len(selections) > 0:
                sel_text = selections[0].GetText(500)
                results['selection_text'] = repr(sel_text[:100]) if sel_text else "(none)"
        except Exception as e:
            results['selection'] = f"error: {e}"
        
        # Get the document text directly
        try:
            direct_text = doc_range.GetText(500)
            results['direct_text'] = repr(direct_text[:200]) if direct_text else "(empty)"
        except Exception as e:
            results['direct_text'] = f"error: {e}"
        
        # Try move and compare - check if we can move to start/end and if they differ
        try:
            start_clone = doc_range.Clone()
            end_clone = doc_range.Clone()
            
            # MoveEndpointByUnit to start
            start_clone.MoveEndpointByUnit(0, 0, -10000)  # Move Start endpoint by Character back a lot
            end_clone.MoveEndpointByUnit(1, 0, 10000)    # Move End endpoint by Character forward a lot
            
            # Compare
            compare_result = start_clone.CompareEndpoints(1, end_clone, 0)  # Compare Start's End to End's Start
            results['endpoint_compare'] = compare_result
        except Exception as e:
            results['endpoint_compare'] = f"error: {e}"
        
        # Try getting bounding rectangles of the document range
        try:
            rects = doc_range.GetBoundingRectangles()
            if rects:
                results['bounding_rect_count'] = len(rects) // 4  # 4 values per rect (l,t,r,b)
                if len(rects) >= 4:
                    results['first_rect'] = f"({rects[0]:.0f}, {rects[1]:.0f}, {rects[2]:.0f}, {rects[3]:.0f})"
        except Exception as e:
            results['bounding_rects'] = f"error: {e}"
            
    except Exception as e:
        results['error'] = str(e)
    
    return results


def main():
    print("=" * 70)
    print("Analyzing Chat Input Text Range")
    print("=" * 70)
    
    windows = find_all_vscode_windows()
    print(f"\nFound {len(windows)} VS Code window(s)\n")
    
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    for w in windows[:3]:
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
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if rect.left < -5000 or rect.top < -5000:
                continue
                
            print(f"\n  [Chat Input {i}] at ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})")
            
            analysis = analyze_text_range(editor)
            for key, val in analysis.items():
                print(f"    {key}: {val}")
    
    print("\n" + "=" * 70)
    print("Done - no keystrokes sent!")
    print("=" * 70)


if __name__ == "__main__":
    main()
