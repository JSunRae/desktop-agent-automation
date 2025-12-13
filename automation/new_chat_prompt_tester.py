"""Generate master prompts and paste them into a brand-new Copilot chat panel."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

import keyboard  # type: ignore[import-not-found]
import uiautomation as auto

try:
    from LAGACY_auto_allow_copilot import (
        MASTER_AGENT_MAX_CHARS,
        MASTER_AGENT_MAX_DOCS,
        MASTER_AGENT_MODEL,
        click_button_instantly,
        find_all_vscode_windows,
        get_cursor_pos,
        set_cursor_pos,
        set_foreground_window,
    )
    from automation.master_prompt_orchestrator import MasterPromptOrchestrator
except ModuleNotFoundError:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from LAGACY_auto_allow_copilot import (
        MASTER_AGENT_MAX_CHARS,
        MASTER_AGENT_MAX_DOCS,
        MASTER_AGENT_MODEL,
        click_button_instantly,
        find_all_vscode_windows,
        get_cursor_pos,
        set_cursor_pos,
        set_foreground_window,
    )
    from automation.master_prompt_orchestrator import MasterPromptOrchestrator

NEW_CHAT_KEYWORD = "new chat"
CHAT_INPUT_KEYWORDS: Tuple[str, ...] = (
    "new chat editor",
    "chat input",
    "message copilot",
    "type your instructions",
    "start typing",
    "prompt copilot",
    "send a message",
)


def _iter_controls(control: auto.Control, *, max_depth: int = 45):
    stack: list[Tuple[auto.Control, int]] = [(control, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            continue
        yield node
        try:
            children = node.GetChildren()
        except KeyboardInterrupt:
            raise
        except Exception:
            continue
        for child in children:
            stack.append((child, depth + 1))


def _find_new_chat_button(vs_win: auto.Control) -> Optional[auto.Control]:
    for ctrl in _iter_controls(vs_win, max_depth=40):
        if isinstance(ctrl, auto.ButtonControl):
            name = (ctrl.Name or "").strip().lower()
            if name and NEW_CHAT_KEYWORD in name:
                return ctrl
    return None


def _find_chat_input_control(vs_win: auto.Control) -> Optional[auto.Control]:
    best: Optional[auto.Control] = None
    best_score = -1.0
    for ctrl in _iter_controls(vs_win, max_depth=55):
        if not isinstance(ctrl, (auto.EditControl, auto.DocumentControl, auto.TextControl)):
            continue
        name = (ctrl.Name or "").strip().lower()
        score = 0.0
        if any(keyword in name for keyword in CHAT_INPUT_KEYWORDS):
            score += 5.0
        try:
            rect = ctrl.BoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width > 0 and height > 0:
                score += height / 200.0
                score += rect.top / 10000.0
        except Exception:
            pass
        if score > best_score:
            best_score = score
            best = ctrl
    return best


def _focus_control(control: Optional[auto.Control]) -> bool:
    if control is None:
        return False
    original_pos = get_cursor_pos()
    try:
        try:
            control.SetFocus()
            return True
        except Exception:
            rect = control.BoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return False
            center_x = rect.left + width // 2
            center_y = rect.top + height // 2
            set_cursor_pos(center_x, center_y)
            time.sleep(0.05)
            control.Click(simulateMove=False)
            return True
    finally:
        set_cursor_pos(original_pos[0], original_pos[1])


def _wait_for_new_chat_button(timeout: float) -> Tuple[Optional[auto.Control], Optional[auto.Control]]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        windows = find_all_vscode_windows()
        for vs_win in windows:
            btn = _find_new_chat_button(vs_win)
            if btn is not None and btn.Exists(0.2):
                return vs_win, btn
        time.sleep(0.4)
    return None, None


def _wait_for_chat_input(vs_win: auto.Control, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl = _find_chat_input_control(vs_win)
        if ctrl and ctrl.Exists(0.2) and _focus_control(ctrl):
            return True
        time.sleep(0.2)
    return False


def _type_prompts(text: str) -> None:
    sanitized = text.strip()
    if not sanitized:
        raise RuntimeError("Prompt batch is empty; nothing to paste.")
    keyboard.send('ctrl+a')
    time.sleep(0.05)
    keyboard.send('delete')
    time.sleep(0.1)
    keyboard.write(sanitized, delay=0)


def _load_prompts(
    *,
    orchestrator: MasterPromptOrchestrator,
    reuse_latest: bool,
) -> Tuple[str, Path]:
    if reuse_latest:
        latest_path = orchestrator.output_dir / "latest.txt"
        if not latest_path.exists():
            raise FileNotFoundError(
                f"{latest_path} not found. Run without --reuse-latest to create it first."
            )
        return latest_path.read_text(encoding="utf-8").strip(), latest_path

    result = orchestrator.generate_prompt_batch()
    if not result:
        raise RuntimeError("OpenAI returned no prompts. Check logs for errors.")
    raw_text = (result.raw_text or "").strip()
    if not raw_text:
        raw_text = result.output_path.read_text(encoding="utf-8").strip()
    return raw_text, result.output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate master prompts via OpenAI and paste them into a brand-new Copilot chat panel."
        )
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        help="Override document directories (defaults to MASTER_AGENT docs roots)",
    )
    parser.add_argument(
        "--reuse-latest",
        action="store_true",
        help="Skip the OpenAI call and reuse tasks/generated_prompts/latest.txt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate (or load) prompts but skip UI automation and pasting",
    )
    parser.add_argument(
        "--window-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for a VS Code window with the New Chat button",
    )
    parser.add_argument(
        "--panel-timeout",
        type=float,
        default=6.0,
        help="Seconds to wait for the blank chat editor after clicking New Chat",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=MASTER_AGENT_MAX_DOCS,
        help="Max number of documents to send to OpenAI",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=MASTER_AGENT_MAX_CHARS,
        help="Max characters per document",
    )
    parser.add_argument(
        "--model",
        default=MASTER_AGENT_MODEL,
        help="Override the OpenAI model for prompt generation",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if sys.platform != "win32":
        raise SystemExit("This tester only runs on Windows because it drives the VS Code UI.")

    parser = _build_parser()
    args = parser.parse_args(argv)

    docs_dirs = [Path(p) for p in args.docs] if args.docs else None
    orchestrator = MasterPromptOrchestrator(
        docs_dirs=docs_dirs,
        max_docs=args.max_docs,
        max_chars=args.max_chars,
        model=args.model,
    )

    print("[1/4] Collecting and generating master prompts...")
    prompts_text, source_path = _load_prompts(
        orchestrator=orchestrator,
        reuse_latest=args.reuse_latest,
    )
    print(f"      Loaded {len(prompts_text)} characters from {source_path}")

    if args.dry_run:
        print("Dry-run requested; skipping UI automation.")
        return 0

    print("[2/4] Looking for a VS Code window with the Copilot 'New Chat' button...")
    vs_win, button = _wait_for_new_chat_button(args.window_timeout)
    if not vs_win or not button:
        raise SystemExit("Could not find a VS Code Copilot chat window with a 'New Chat' button.")

    hwnd = getattr(vs_win, "NativeWindowHandle", None)
    if hwnd:
        set_foreground_window(hwnd)
        time.sleep(0.2)

    print("[3/4] Opening a blank Copilot chat panel via the New Chat button...")
    click_button_instantly(button)
    time.sleep(0.4)
    keyboard.send('ctrl+n')

    if not _wait_for_chat_input(vs_win, args.panel_timeout):
        raise SystemExit(
            "New chat panel did not expose a focusable editor. Make sure Copilot chat view is visible."
        )

    print("[4/4] Pasting master prompts into the blank panel...")
    _type_prompts(prompts_text)
    print("✓ Prompts pasted into a fresh Copilot chat panel. Review and submit when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
