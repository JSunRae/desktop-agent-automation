"""
Test to detect text in chat input by analyzing children and text lines.
NO keystrokes, NO clipboard - just UI Automation property inspection.
"""
import uiautomation as auto
import ctypes
from typing import List, Optional

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


def find_all_descendant_controls(control, max_depth=10) -> List[dict]:
    """Find all descendant controls with their properties."""
    results = []
    
    def collect(ctrl, depth=0):
        if depth > max_depth:
            return
        try:
            info = {
                'depth': depth,
                'type': ctrl.ControlTypeName,
                'name': (ctrl.Name or "")[:50],
                'class': getattr(ctrl, 'ClassName', '') or '',
                'automation_id': getattr(ctrl, 'AutomationId', '') or '',
            }
            try:
                rect = ctrl.BoundingRectangle
                info['bounds'] = f"({rect.left},{rect.top},{rect.right},{rect.bottom})"
                info['size'] = f"{rect.width()}x{rect.height()}"
            except:
                info['bounds'] = 'N/A'
            results.append(info)
            
            for child in ctrl.GetChildren():
                collect(child, depth + 1)
        except Exception:
            pass
    
    collect(control)
    return results


def find_text_children(editor) -> List[auto.Control]:
    """Find any Text controls that might contain the typed text."""
    text_controls = []
    
    def search(control, depth=0, max_depth=15):
        if depth > max_depth:
            return
        try:
            if control.ControlType == auto.ControlType.TextControl:
                text_controls.append(control)
            for child in control.GetChildren():
                search(child, depth + 1)
        except:
            pass
    
    search(editor)
    return text_controls


def get_sibling_or_parent_text(editor) -> Optional[str]:
    """Look for sibling or parent controls that might contain the input text."""
    try:
        # Check parent
        parent = editor.GetParentControl()
        if parent:
            # Look at siblings
            for sibling in parent.GetChildren():
                if sibling != editor:
                    try:
                        name = sibling.Name
                        if name and len(name) > 0 and "editor is not accessible" not in name.lower():
                            return f"Sibling: {name[:100]}"
                    except:
                        pass
            
            # Look at parent's name
            try:
                parent_name = parent.Name
                if parent_name and len(parent_name) > 5:
                    return f"Parent: {parent_name[:100]}"
            except:
                pass
    except:
        pass
    return None


def analyze_editor_structure(editor) -> dict:
    """Analyze the editor structure to find where text might be stored."""
    results = {
        'has_children': False,
        'child_count': 0,
        'text_controls': [],
        'edit_controls': [],
        'group_controls': [],
        'sibling_text': None,
    }
    
    try:
        children = list(editor.GetChildren())
        results['has_children'] = len(children) > 0
        results['child_count'] = len(children)
        
        for child in children:
            try:
                info = {
                    'type': child.ControlTypeName,
                    'name': (child.Name or "")[:60],
                }
                try:
                    rect = child.BoundingRectangle
                    info['size'] = f"{rect.width()}x{rect.height()}"
                except:
                    pass
                
                if child.ControlType == auto.ControlType.TextControl:
                    results['text_controls'].append(info)
                elif child.ControlType == auto.ControlType.EditControl:
                    results['edit_controls'].append(info)
                elif child.ControlType == auto.ControlType.GroupControl:
                    results['group_controls'].append(info)
            except:
                pass
        
        results['sibling_text'] = get_sibling_or_parent_text(editor)
        
    except Exception as e:
        results['error'] = str(e)
    
    return results


def check_editor_line_count(editor) -> dict:
    """Try to determine if editor has content by checking line-related properties."""
    results = {}
    
    # Check editor height - if there's multi-line text, height might be larger
    try:
        rect = editor.BoundingRectangle
        results['editor_height'] = rect.height()
        results['editor_width'] = rect.width()
    except:
        pass
    
    # Try to get scroll info - if there's text that scrolls, there might be content
    try:
        scroll_pattern = editor.GetScrollPattern()
        if scroll_pattern:
            results['has_scroll'] = True
            results['v_scroll_percent'] = scroll_pattern.VerticalScrollPercent
            results['h_scroll_percent'] = scroll_pattern.HorizontalScrollPercent
            results['v_view_size'] = scroll_pattern.VerticalViewSize
        else:
            results['has_scroll'] = False
    except Exception as e:
        results['scroll_error'] = str(e)
    
    return results


def main():
    print("=" * 70)
    print("Analyzing Editor Structure to Find Text")
    print("=" * 70)
    print("\nLooking for patterns that indicate text is present...")
    print("NO keystrokes will be sent.\n")
    
    windows = find_all_vscode_windows()
    print(f"Found {len(windows)} VS Code window(s)\n")
    
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    
    for w in windows[:3]:
        try:
            is_foreground = w.NativeWindowHandle == hwnd
        except:
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
                
            print(f"\n  [Chat Input {i}] at ({rect.left}, {rect.top})")
            print(f"    Size: {rect.width()}x{rect.height()}")
            
            # Check structure
            structure = analyze_editor_structure(editor)
            print(f"    Has children: {structure['has_children']}, count: {structure['child_count']}")
            if structure['text_controls']:
                print(f"    Text controls: {structure['text_controls']}")
            if structure['sibling_text']:
                print(f"    Nearby text: {structure['sibling_text']}")
            
            # Check line info
            line_info = check_editor_line_count(editor)
            if 'has_scroll' in line_info:
                print(f"    Has scroll: {line_info['has_scroll']}")
                if line_info.get('v_scroll_percent', -1) >= 0:
                    print(f"    Scroll%: V={line_info.get('v_scroll_percent')}, H={line_info.get('h_scroll_percent')}")
            
            # Find text children
            text_ctrls = find_text_children(editor)
            if text_ctrls:
                print(f"    Found {len(text_ctrls)} Text control(s) in subtree:")
                for tc in text_ctrls[:5]:
                    try:
                        print(f"      - '{tc.Name[:60] if tc.Name else '(no name)'}...'")
                    except:
                        pass
    
    print("\n" + "=" * 70)
    print("Analysis complete - no keystrokes sent!")
    print("=" * 70)


if __name__ == "__main__":
    main()
