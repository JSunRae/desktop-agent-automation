"""
Test script to verify panel detection and text box state detection.

Tests:
1. Find all VS Code windows on current desktop
2. For each window, detect:
   - Panel status (RUNNING vs IDLE/FINISHED)
   - Whether chat input has text
3. Report findings for validation
"""

import time
from datetime import datetime
import uiautomation as auto

# Import from panel_tracker
from automation.panel_tracker import (
    detect_panel_running_state,
    detect_panel_state_detailed,
    get_comprehensive_panel_state,
    find_chat_editor_control,
    get_chat_input_text,
    _check_editor_has_text_via_clipboard,
    get_panel_output_text,
    PanelStatus,
    IdleReason,
)


VSCODE_TITLE_SUFFIX = " - Visual Studio Code"


def find_all_vscode_windows(timeout: float = 0.5) -> list:
    """Find ALL VS Code windows by title suffix."""
    vscode_windows = []
    try:
        for w in auto.GetRootControl().GetChildren():
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(timeout):
                            vscode_windows.append(w)
                except Exception:
                    continue
    except Exception as e:
        print(f"  ⚠️  Warning: UI enumeration error: {e}")
    return vscode_windows


def check_chat_input_state(vs_win: auto.Control) -> dict:
    """
    Check the state of the chat input box in a VS Code window.
    
    Returns a dictionary with:
    - has_editor: bool - whether we found the editor control
    - has_text: bool - whether the editor has text
    - text_preview: str - first 50 chars of text (if any)
    - method_used: str - which method was used to get the text
    """
    import ctypes
    
    result = {
        "has_editor": False,
        "has_text": False,
        "text_preview": "",
        "method_used": "none",
    }
    
    # Save current window
    original_window = ctypes.windll.user32.GetForegroundWindow()
    
    try:
        # Find the chat editor control
        editor = find_chat_editor_control(vs_win)
        
        if not editor:
            return result
        
        result["has_editor"] = True
        
        # Method 1: Try TextPattern directly (no window switch needed)
        try:
            text_pattern = editor.GetTextPattern()
            if text_pattern:
                doc_range = text_pattern.DocumentRange
                if doc_range:
                    text = doc_range.GetText(-1)
                    if text:
                        text = text.strip()
                        result["has_text"] = len(text) > 0
                        result["text_preview"] = text[:50] if text else ""
                        result["method_used"] = "TextPattern"
                        return result
        except Exception:
            pass
        
        # Method 2: Try ValuePattern (no window switch needed)
        try:
            value_pattern = editor.GetValuePattern()
            if value_pattern:
                value = value_pattern.Value
                if value is not None:
                    value = value.strip()
                    result["has_text"] = len(value) > 0
                    result["text_preview"] = value[:50] if value else ""
                    result["method_used"] = "ValuePattern"
                    return result
        except Exception:
            pass
        
        # Method 3: Clipboard method (requires window switch)
        try:
            # Activate VS Code window
            vs_win.SetActive()
            time.sleep(0.15)
            
            # Focus the editor
            editor.SetFocus()
            time.sleep(0.1)
            
            # Use clipboard to check for text
            has_text, text = _check_editor_has_text_via_clipboard(editor)
            result["has_text"] = has_text
            result["text_preview"] = text[:50] if text else ""
            result["method_used"] = "clipboard"
            
        except Exception as e:
            result["method_used"] = f"error: {e}"
        
        finally:
            # Restore original window
            if original_window:
                time.sleep(0.1)
                ctypes.windll.user32.SetForegroundWindow(original_window)
        
        return result
        
    except Exception as e:
        print(f"  Error checking chat input: {e}")
        return result


def test_panel_detection():
    """Main test function to check panel detection on current desktop."""
    print("=" * 70)
    print(f"Panel Detection Test - {datetime.now()}")
    print("=" * 70)
    
    # Find all VS Code windows
    print("\n📋 Finding VS Code windows on current desktop...")
    windows = find_all_vscode_windows()
    
    if not windows:
        print("  ❌ No VS Code windows found!")
        return
    
    print(f"  ✓ Found {len(windows)} VS Code window(s)")
    
    # Test each window
    results = []
    
    for i, vs_win in enumerate(windows, 1):
        try:
            title = vs_win.Name or "Unknown"
            print(f"\n{'─' * 70}")
            print(f"Window {i}: {title[:60]}...")
            print("─" * 70)
            
            # Get comprehensive state
            state = get_comprehensive_panel_state(vs_win)
            
            # Detect running state
            is_running = detect_panel_running_state(vs_win)
            
            # Get detailed state
            detailed = detect_panel_state_detailed(vs_win)
            
            # Check chat input state
            input_state = check_chat_input_state(vs_win)
            
            # Collect output sample
            output_text = get_panel_output_text(vs_win)
            output_sample = output_text[-100:] if output_text else "(no output)"
            
            result = {
                "title": title,
                "has_chat_panel": state["has_chat_panel"],
                "is_running": is_running,
                "has_send_button": detailed["has_send_button"],
                "idle_reason": state["idle_reason"],
                "needs_action": state["needs_action"],
                "chat_input": input_state,
                "output_sample": output_sample,
            }
            results.append(result)
            
            # Print findings
            status_icon = "■ WORKING" if is_running else "▶ IDLE"
            print(f"  Status: [{status_icon}]")
            print(f"  Has chat panel: {state['has_chat_panel']}")
            print(f"  Is running (Cancel visible): {is_running}")
            print(f"  Has Send button: {detailed['has_send_button']}")
            
            if state["idle_reason"]:
                reason_str = state["idle_reason"].value if state["idle_reason"] else "unknown"
                print(f"  Idle reason: {reason_str}")
            
            print(f"  Needs action: {state['needs_action']}")
            
            # Chat input state
            print(f"\n  Chat Input Box:")
            print(f"    Found editor: {input_state['has_editor']}")
            print(f"    Has text: {input_state['has_text']}")
            if input_state["has_text"]:
                print(f"    Text preview: '{input_state['text_preview']}'")
            print(f"    Method used: {input_state['method_used']}")
            
            # Output sample
            if output_sample and output_sample != "(no output)":
                print(f"\n  Output sample (last 100 chars):")
                print(f"    ...{output_sample}")
            
        except Exception as e:
            print(f"  ❌ Error analyzing window: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    running_count = sum(1 for r in results if r["is_running"])
    idle_count = len(results) - running_count
    with_text_count = sum(1 for r in results if r["chat_input"]["has_text"])
    without_text_count = sum(1 for r in results if r["chat_input"]["has_editor"] and not r["chat_input"]["has_text"])
    
    print(f"\n  Total windows: {len(results)}")
    print(f"  Running (Cancel visible): {running_count}")
    print(f"  Idle (Send visible): {idle_count}")
    print(f"\n  Chat input boxes with text: {with_text_count}")
    print(f"  Chat input boxes empty: {without_text_count}")
    
    # Validation for user's scenario
    print("\n" + "─" * 70)
    print("VALIDATION (User expects 1 running + 1 finished):")
    print("─" * 70)
    
    if running_count == 1 and idle_count == 1:
        print("  ✓ CORRECT: Found 1 running and 1 idle/finished panel")
    else:
        print(f"  ⚠ Expected 1 running + 1 idle, found {running_count} running + {idle_count} idle")
    
    print("\n  Expected behavior:")
    print("  - Running panel: Should have text in input box OR be actively working")
    print("  - Finished panel: Should have EMPTY input box")
    
    for r in results:
        status = "RUNNING" if r["is_running"] else "FINISHED/IDLE"
        has_text = r["chat_input"]["has_text"]
        text_status = "HAS TEXT" if has_text else "EMPTY"
        
        print(f"\n  '{r['title'][:50]}...'")
        print(f"    Panel: {status}")
        print(f"    Input box: {text_status}")
        
        if not r["is_running"] and has_text:
            print(f"    ⚠ WARNING: Finished panel has text - will NOT send new prompt to preserve user's text")
        elif not r["is_running"] and not has_text:
            print(f"    ✓ OK: Finished panel has empty input - can send follow-up prompt")


if __name__ == "__main__":
    test_panel_detection()
