"""UI automation helpers for interacting with Copilot chat panels."""

from __future__ import annotations

import time
from typing import Any, List, Optional, TYPE_CHECKING, cast

from automation.config import ENABLE_CLIPBOARD_TEXT_READING, ENABLE_SEND_TO_INACTIVE_PANELS

if TYPE_CHECKING:
    import uiautomation as auto


# Runtime tracking for panels with user text (never send to these)
_panels_with_user_text: set[str] = set()


def iter_controls(control: "auto.Control", *, max_depth: int = 45):
    stack: list[tuple["auto.Control", int]] = [(control, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            continue
        yield node
        try:
            children = node.GetChildren()
        except Exception:
            continue
        for child in children:
            stack.append((child, depth + 1))


def find_chat_input_box(vs_win: "auto.Control") -> Optional["auto.Control"]:
    import uiautomation as auto

    def search_for_input(control: auto.Control, depth: int = 0, max_depth: int = 50) -> Optional[auto.Control]:
        if depth > max_depth:
            return None
        try:
            if control.ControlType == auto.ControlType.WindowControl:
                class_name = getattr(control, "ClassName", "") or ""
                if "Chrome_RenderWidgetHostHWND" in class_name:
                    if control.Exists(0.1):
                        try:
                            name = control.Name or ""
                            if not name:
                                return control
                        except Exception:
                            return control

            if control.ControlType == auto.ControlType.EditControl:
                if control.Exists(0.1):
                    return control

            for child in control.GetChildren():
                result = search_for_input(child, depth + 1, max_depth)
                if result:
                    return result
        except Exception:
            return None

        return None

    return search_for_input(vs_win)


def find_send_button(vs_win: "auto.Control") -> Optional["auto.Control"]:
    import uiautomation as auto

    def search_for_send(control: auto.Control, depth: int = 0, max_depth: int = 50) -> Optional[auto.Control]:
        if depth > max_depth:
            return None
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name or ""
                if "Send" in name and "Cancel" not in name:
                    if control.Exists(0.1):
                        return control

            for child in control.GetChildren():
                result = search_for_send(child, depth + 1, max_depth)
                if result:
                    return result
        except Exception:
            return None
        return None

    return search_for_send(vs_win)


def get_panel_output_text(vs_win: "auto.Control", max_depth: int = 60) -> str:
    text_parts: List[str] = []

    def collect_text(control: "auto.Control", depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            name = control.Name
            if name and len(name) > 20:
                if not any(skip in name for skip in ["Ctrl+", "Alt+", "button", "Button"]):
                    text_parts.append(name)
            for child in control.GetChildren():
                collect_text(child, depth + 1)
        except Exception:
            return

    collect_text(vs_win)
    return "\n".join(text_parts)


def find_chat_editor_control(vs_win: "auto.Control") -> Optional["auto.Control"]:
    import uiautomation as auto

    found_editors: List["auto.Control"] = []

    def search_for_editor(control: "auto.Control", depth: int = 0, max_depth: int = 50) -> None:
        if depth > max_depth:
            return
        try:
            if control.ControlType == auto.ControlType.EditControl:
                name = control.Name or ""
                if "editor is not accessible" in name.lower() or "screen reader" in name.lower():
                    if control.Exists(0.1):
                        found_editors.append(control)
                        return

            for child in control.GetChildren():
                search_for_editor(child, depth + 1, max_depth)
                if found_editors:
                    return
        except Exception:
            return

    search_for_editor(vs_win)
    return found_editors[0] if found_editors else None


def get_chat_input_text(vs_win: "auto.Control") -> Optional[str]:
    try:
        editor = find_chat_editor_control(vs_win)
        if not editor:
            return None

        editor_any = cast(Any, editor)

        try:
            text_pattern = editor_any.GetTextPattern()
            if text_pattern:
                doc_range = text_pattern.DocumentRange
                if doc_range:
                    text = doc_range.GetText(-1)
                    if text:
                        return text.strip()
        except Exception:
            pass

        try:
            value_pattern = editor_any.GetValuePattern()
            if value_pattern:
                value = value_pattern.Value
                if value:
                    return value.strip()
        except Exception:
            pass

        try:
            legacy = editor_any.GetLegacyIAccessiblePattern()
            if legacy:
                value = legacy.Value
                if value:
                    return value.strip()
        except Exception:
            pass

        return _get_chat_input_via_clipboard(vs_win, editor)

    except Exception as e:
        print(f"[PanelTracker] Error getting chat input text: {e}")
        return None


def _get_chat_input_via_clipboard(vs_win: "auto.Control", editor: "auto.Control") -> Optional[str]:
    if not ENABLE_CLIPBOARD_TEXT_READING:
        return None

    import ctypes
    import subprocess
    import uiautomation as auto

    try:
        original_window = ctypes.windll.user32.GetForegroundWindow()
        try:
            cast(Any, vs_win).SetActive()
            time.sleep(0.2)

            auto.SendKeys("{Escape}")
            time.sleep(0.2)

            subprocess.run(
                ["powershell", "-Command", "Set-Clipboard -Value ''"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(0.03)

            auto.SendKeys("^l")
            time.sleep(0.2)
            auto.SendKeys("^a")
            time.sleep(0.1)
            auto.SendKeys("^c")
            time.sleep(0.2)

            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            auto.SendKeys("{End}")
            time.sleep(0.02)

            clipboard_text = result.stdout.strip() if result.returncode == 0 else ""
            return clipboard_text
        finally:
            if original_window:
                time.sleep(0.05)
                ctypes.windll.user32.SetForegroundWindow(original_window)
    except Exception as e:
        print(f"[PanelTracker] Error getting chat input via clipboard: {e}")
        return None


def _get_clipboard_text() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["powershell", "-command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _set_clipboard_text(text: str) -> None:
    import subprocess

    try:
        escaped = text.replace("'", "''")
        subprocess.run(
            ["powershell", "-command", f"Set-Clipboard -Value '{escaped}'"],
            capture_output=True,
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return


def _check_editor_has_text_via_clipboard(editor: "auto.Control") -> tuple[bool, str]:
    if not ENABLE_CLIPBOARD_TEXT_READING:
        return (False, "")

    import uiautomation as auto

    marker = "__COPILOT_EMPTY_CHECK__"
    _set_clipboard_text(marker)

    try:
        auto.SendKeys("{Ctrl}a")
        time.sleep(0.05)
        auto.SendKeys("{Ctrl}c")
        time.sleep(0.1)

        clipboard_text = _get_clipboard_text()

        auto.SendKeys("{End}")
        time.sleep(0.02)

        if clipboard_text == marker:
            return (False, "")
        return (True, clipboard_text)
    except Exception as e:
        print(f"[PanelTracker] Error checking editor text: {e}")
        return (False, "")


def send_text_to_chat(vs_win: "auto.Control", text: str) -> bool:
    if not ENABLE_SEND_TO_INACTIVE_PANELS:
        print("[PanelTracker] send_text_to_chat BLOCKED - feature disabled (ENABLE_SEND_TO_INACTIVE_PANELS=false)")
        return False

    import ctypes
    import uiautomation as auto  # noqa: F401

    try:
        window_title = vs_win.Name or "Unknown"

        if window_title in _panels_with_user_text:
            print(f"[PanelTracker] Skipping panel (has user text): '{window_title[:50]}...'")
            return False

        editor = find_chat_editor_control(vs_win)
        original_window = ctypes.windll.user32.GetForegroundWindow()

        try:
            cast(Any, vs_win).SetActive()
            time.sleep(0.1)

            if editor:
                try:
                    editor.SetFocus()
                    time.sleep(0.1)

                    has_text, existing_text = _check_editor_has_text_via_clipboard(editor)
                    if has_text:
                        _panels_with_user_text.add(window_title)
                        print(
                            f"[PanelTracker] Chat input has existing text ('{existing_text[:30]}...'), skipping send in '{window_title[:50]}...'"
                        )
                        print("[PanelTracker] Panel marked as 'has user text' - will skip for rest of run")
                        if original_window:
                            time.sleep(0.05)
                            ctypes.windll.user32.SetForegroundWindow(original_window)
                        return False
                except Exception as e:
                    print(f"[PanelTracker] Error focusing/checking editor: {e}")
            else:
                input_box = find_chat_input_box(vs_win)
                if input_box:
                    try:
                        input_box.Click(simulateMove=False)
                        time.sleep(0.05)
                    except Exception:
                        pass

            auto.SendKeys(text)
            time.sleep(0.05)

            send_btn = find_send_button(vs_win)
            if send_btn is None:
                auto.SendKeys("{Enter}")
                time.sleep(0.05)
            else:
                try:
                    send_btn.Click(simulateMove=False)
                    time.sleep(0.05)
                except Exception:
                    auto.SendKeys("{Enter}")

            return True
        finally:
            if original_window:
                time.sleep(0.05)
                ctypes.windll.user32.SetForegroundWindow(original_window)
    except Exception as e:
        print(f"[PanelTracker] Error sending text to chat: {e}")
        return False
