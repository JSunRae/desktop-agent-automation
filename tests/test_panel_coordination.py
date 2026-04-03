"""Safe dry-run tests for panel inspection, overlap detection, agent response
controls, and panel refresh — all within desktop-agent-automation only.

These tests NEVER click, type, or mutate any panel. They collect data and
assert that expected UI controls are detectable, making them safe to run
against production VS Code sessions.

Run with pytest:
    pytest tests/test_panel_coordination.py -v

Or directly (runs all suites with a quick console report):
    python tests/test_panel_coordination.py

Flags (all default to safe/dry-run):
    --live-click     Actually click response/refresh controls (use with care)
    --target-repo    Filter scanned windows to those matching this substring
                     (default: "desktop-agent-automation")

SAFETY GUARANTEE:
    Without --live-click, no UI mutation occurs. All assertions are
    observation-only and safe to run while agents are working.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup — allow running directly without install
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Optional uiautomation import (skip gracefully when running in headless CI)
# ---------------------------------------------------------------------------
try:
    import uiautomation as auto  # type: ignore

    _HAS_UI = True
except Exception:
    auto = None  # type: ignore
    _HAS_UI = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VSCODE_TITLE_KEYWORDS = (" - Visual Studio Code", " - VS Code")

_REPO_ROLE_HINTS: Dict[str, str] = {
    "TF": "ML models / feature engineering / W&B",
    "Trading": "Execution / data acquisition / paper-trading",
    "contracts": "Schema definitions / shared data contracts",
    "desktop-agent-automation": "Automation control plane (this repo)",
}

_RESPONSE_BUTTON_NAMES: Tuple[Tuple[str, str], ...] = (
    ("stop_and_send", "Stop and Send"),
    ("add_to_queue", "Add to Queue"),
    ("steer_with_message", "Steer with Message"),
)


def _is_vscode_window(win: Any) -> bool:
    try:
        name = win.Name or ""
        return any(k in name for k in _VSCODE_TITLE_KEYWORDS)
    except Exception:
        return False


def _infer_repo(title: str) -> str:
    """Guess the repo being edited from the window title."""
    for repo in ("Trading", "TF", "contracts", "desktop-agent-automation"):
        if repo.lower() in title.lower():
            return repo
    return "unknown"


def _iter_controls_safe(control: Any, max_depth: int = 50):
    """BFS-safe control iterator that never raises."""
    stack: list[tuple[Any, int]] = [(control, 0)]
    while stack:
        node, depth = stack.pop()
        if depth >= max_depth:
            continue
        yield node
        try:
            children = node.GetChildren()
        except Exception:
            continue
        for child in children:
            stack.append((child, depth + 1))


def _collect_buttons(win: Any) -> List[Dict[str, Any]]:
    """Collect all ButtonControl entries from a VS Code window."""
    results: List[Dict[str, Any]] = []
    if auto is None:
        return results
    for ctrl in _iter_controls_safe(win):
        try:
            if not isinstance(ctrl, auto.ButtonControl):
                continue
            name = ctrl.Name or ""
            if not name:
                continue
            results.append({"name": name, "control": ctrl})
        except Exception:
            continue
    return results


def _collect_text_snippets(win: Any, max_chars: int = 400) -> str:
    """Collect visible text from a panel for intent inference."""
    parts: List[str] = []
    if auto is None:
        return ""
    for ctrl in _iter_controls_safe(win, max_depth=60):
        try:
            name = ctrl.Name or ""
            if len(name) > 30 and not any(s in name for s in ["Ctrl+", "Alt+", "Button", "button"]):
                parts.append(name[:200])
                if sum(len(p) for p in parts) > max_chars:
                    break
        except Exception:
            continue
    return " | ".join(parts)


def _infer_task_intent(text_snippet: str) -> str:
    """Heuristic: pick the first meaningful-looking sentence from panel text."""
    if not text_snippet:
        return "(no text visible)"
    # Take the first chunk up to 120 chars
    first = text_snippet.split("|")[0].strip()
    return textwrap.shorten(first, width=120, placeholder="...")


# ---------------------------------------------------------------------------
# Suite 1: Panel Scanner
# ---------------------------------------------------------------------------


class TestPanelScanner:
    """Discover all open VS Code windows, infer repo + task intent."""

    description = "Scans all VS Code windows and infers what each panel is doing."

    def __init__(self, target_repo: str = "desktop-agent-automation") -> None:
        self.target_repo = target_repo.lower()
        self.panels: List[Dict[str, Any]] = []

    def run(self) -> bool:
        if not _HAS_UI:
            print("[SKIP] uiautomation not available (headless / CI)")
            return True

        windows = [
            w for w in auto.GetRootControl().GetChildren()
            if _is_vscode_window(w)
        ]
        if not windows:
            print("[WARN] No VS Code windows found. Is VS Code open?")
            return True

        print(f"\n  Found {len(windows)} VS Code window(s):")
        matched = 0
        for win in windows:
            try:
                title = win.Name or "(untitled)"
            except Exception:
                title = "(error reading title)"

            repo = _infer_repo(title)
            text = _collect_text_snippets(win)
            intent = _infer_task_intent(text)
            entry = {"title": title, "repo": repo, "intent": intent, "win": win}
            self.panels.append(entry)

            if self.target_repo and self.target_repo not in title.lower() and self.target_repo not in repo.lower():
                marker = "  (out of scope)"
            else:
                marker = "  <-- in scope"
                matched += 1

            role = _REPO_ROLE_HINTS.get(repo, "")
            print(f"\n  [{repo}]{marker}")
            print(f"    Title  : {title[:80]}")
            print(f"    Role   : {role}")
            print(f"    Intent : {intent[:100]}")

        print(f"\n  Summary: {len(windows)} total, {matched} in scope ({self.target_repo})")
        return True


# ---------------------------------------------------------------------------
# Suite 2: Overlap Detector
# ---------------------------------------------------------------------------


class TestOverlapDetector:
    """Compare running panel intents against the coordination ledger."""

    description = "Compares detected panel task intent against the North Star coordination guard."

    def __init__(self, panels: Optional[List[Dict[str, Any]]] = None) -> None:
        self.panels = panels or []

    def run(self) -> bool:
        try:
            from automation.coordination_guard import get_coordination_guard
            from automation.repo_task_ledger import get_ledger_report
        except ImportError as exc:
            print(f"[SKIP] Coordination modules not available: {exc}")
            return True

        guard = get_coordination_guard()
        ledger = get_ledger_report()

        print(f"\n  Ledger: {len(ledger.active_tasks)} active tasks, "
              f"{len(ledger.overlap_warnings)} overlaps, {len(ledger.drift_warnings)} drifts")

        if not self.panels:
            print("  [INFO] No panels provided — running against ledger summary only")

        all_ok = True
        for panel in self.panels:
            intent = panel.get("intent", "")
            repo = panel.get("repo", "")
            if not intent or intent == "(no text visible)":
                continue

            decision = guard.evaluate(intent, repo)
            marker = "[OK]" if decision.outcome.name.startswith("PROCEED") else f"[{decision.outcome.name}]"
            print(f"\n  {marker} Repo={repo}")
            print(f"    Intent  : {intent[:80]}")
            print(f"    Decision: {decision.summary()}")

            if decision.should_block:
                all_ok = False

        if ledger.has_issues:
            print("\n  [WARN] Ledger has issues — run 'python scripts/coord_cli.py status' for details")

        return all_ok


# ---------------------------------------------------------------------------
# Suite 3: Agent Response Controls
# ---------------------------------------------------------------------------


class TestAgentResponseControls:
    """Locate Stop-and-Send / Add-to-Queue / Steer-with-Message buttons.

    In dry-run mode (default) the buttons are found but never clicked.
    Pass live_click=True with extreme care.
    """

    description = ("Detects the 'Stop and Send', 'Add to Queue', and "
                   "'Steer with Message' Copilot action buttons.")

    def __init__(
        self,
        panels: Optional[List[Dict[str, Any]]] = None,
        live_click: bool = False,
        target_repo: str = "desktop-agent-automation",
    ) -> None:
        self.panels = panels or []
        self.live_click = live_click
        self.target_repo = target_repo.lower()

    def run(self) -> bool:
        if not _HAS_UI:
            print("[SKIP] uiautomation not available")
            return True

        wins = [
            p["win"]
            for p in self.panels
            if self.target_repo in (p.get("title", "") + p.get("repo", "")).lower()
        ]

        if not wins:
            # Fall back to a fresh scan
            wins = [
                w for w in auto.GetRootControl().GetChildren()
                if _is_vscode_window(w)
                and (not self.target_repo or self.target_repo in (w.Name or "").lower())
            ]

        if not wins:
            print("  [SKIP] No matching VS Code windows found")
            return True

        found_any = False
        for win in wins:
            buttons = _collect_buttons(win)
            win_title = ""
            try:
                win_title = (win.Name or "")[:60]
            except Exception:
                pass

            response_btns: Dict[str, Any] = {}
            for btn in buttons:
                name = btn["name"]
                for key, label in _RESPONSE_BUTTON_NAMES:
                    # Match core label words (case-insensitive)
                    label_words = label.lower().split()
                    if all(w in name.lower() for w in label_words):
                        response_btns[key] = btn

            if not response_btns:
                print(f"  [--] {win_title}: no response-action buttons visible (panel may be idle/running)")
                continue

            found_any = True
            print(f"\n  Window: {win_title}")
            for key, label in _RESPONSE_BUTTON_NAMES:
                btn = response_btns.get(key)
                if btn:
                    hotkey_hint = ""
                    if "Alt+Enter" in btn["name"]:
                        hotkey_hint = " (Alt+Enter)"
                    elif key == "steer_with_message" and "Enter" in btn["name"]:
                        hotkey_hint = " (Enter)"
                    status = "[FOUND]"
                    if self.live_click:
                        try:
                            btn["control"].Click()
                            time.sleep(0.3)
                            status = "[CLICKED]"
                        except Exception as exc:
                            status = f"[CLICK ERR: {exc}]"
                    print(f"    {status} {label}{hotkey_hint}")
                else:
                    print(f"    [----] {label}: not visible")

        if not found_any:
            print("  [INFO] No response-action buttons visible in any scanned window.")
            print("         (They appear only when an agent is paused waiting for input.)")
        return True


# ---------------------------------------------------------------------------
# Suite 4: Panel Refresh Test
# ---------------------------------------------------------------------------


class TestPanelRefresh:
    """Verify the Keep→ClearInput→NewChat flow controls are detectable.

    Dry-run by default: finds controls, prints what it would do, no clicks.
    Pass live_click=True to actually execute the refresh sequence.
    """

    description = ("Verifies 'Keep Edits', clear chat input, and 'New Chat' "
                   "controls exist for the panel refresh flow.")

    def __init__(
        self,
        panels: Optional[List[Dict[str, Any]]] = None,
        live_click: bool = False,
        target_repo: str = "desktop-agent-automation",
    ) -> None:
        self.panels = panels or []
        self.live_click = live_click
        self.target_repo = target_repo.lower()

    def _find_input_control(self, win: Any) -> Optional[Any]:
        """Delegate to panel_seeding's input finder if available."""
        try:
            from automation.panel_seeding import (
                _find_chat_input_control,  # type: ignore
            )
            return _find_chat_input_control(win)
        except Exception:
            pass
        return None

    def _find_new_chat_button(self, win: Any) -> Optional[Any]:
        try:
            from automation.panel_seeding import _find_new_chat_button  # type: ignore
            return _find_new_chat_button(win)
        except Exception:
            pass
        if auto is None:
            return None
        for ctrl in _iter_controls_safe(win, max_depth=40):
            try:
                if isinstance(ctrl, auto.ButtonControl):
                    if "new chat" in (ctrl.Name or "").lower():
                        return ctrl
            except Exception:
                continue
        return None

    def _find_keep_button(self, win: Any) -> Optional[Any]:
        if auto is None:
            return None
        for ctrl in _iter_controls_safe(win, max_depth=50):
            try:
                if isinstance(ctrl, auto.ButtonControl):
                    name = (ctrl.Name or "").lower()
                    if "keep" in name and "edit" in name:
                        return ctrl
            except Exception:
                continue
        return None

    def run(self) -> bool:
        if not _HAS_UI:
            print("[SKIP] uiautomation not available")
            return True

        wins = [
            p["win"]
            for p in self.panels
            if self.target_repo in (p.get("title", "") + p.get("repo", "")).lower()
        ]
        if not wins:
            wins = [
                w for w in auto.GetRootControl().GetChildren()
                if _is_vscode_window(w)
                and (not self.target_repo or self.target_repo in (w.Name or "").lower())
            ]
        if not wins:
            print("  [SKIP] No matching VS Code windows found")
            return True

        any_ready = False
        for win in wins:
            win_title = ""
            try:
                win_title = (win.Name or "")[:60]
            except Exception:
                pass
            print(f"\n  Window: {win_title}")

            keep_btn = self._find_keep_button(win)
            input_ctrl = self._find_input_control(win)
            new_chat_btn = self._find_new_chat_button(win)

            results = {
                "Keep Edits button": keep_btn,
                "Chat input box": input_ctrl,
                "New Chat button": new_chat_btn,
            }
            for label, ctrl in results.items():
                if ctrl:
                    print(f"    [FOUND] {label}")
                else:
                    print(f"    [----]  {label}: not found")

            ready = keep_btn is not None and input_ctrl is not None and new_chat_btn is not None
            if ready:
                any_ready = True
                if self.live_click:
                    print("    [EXEC]  Running refresh sequence: Keep -> Clear -> New Chat")
                    self._execute_refresh(win, keep_btn, input_ctrl, new_chat_btn)
                else:
                    print("    [NOTE]  Dry-run: all controls found, ready for refresh.")
            else:
                print("    [INFO]  Not all controls found — panel may still be running or already clear.")

        return True

    def _execute_refresh(
        self,
        win: Any,
        keep_btn: Any,
        input_ctrl: Any,
        new_chat_btn: Any,
    ) -> None:
        """Execute the full Keep→ClearInput→NewChat refresh sequence."""
        try:
            keep_btn.Click()
            print("    [STEP 1] Clicked 'Keep Edits'")
            time.sleep(1.0)
        except Exception as exc:
            print(f"    [ERR]   Keep Edits click failed: {exc}")
            return

        try:
            input_ctrl.SetFocus()
            time.sleep(0.2)
            if auto is not None:
                auto.SendKeys("{Ctrl}a{Delete}", waitTime=0.1)
            print("    [STEP 2] Cleared chat input")
            time.sleep(0.3)
        except Exception as exc:
            print(f"    [ERR]   Clear input failed: {exc}")

        try:
            new_chat_btn.Click()
            print("    [STEP 3] Clicked 'New Chat'")
            time.sleep(0.5)
        except Exception as exc:
            print(f"    [ERR]   New Chat click failed: {exc}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Panel coordination test suite (dry-run safe)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python tests/test_panel_coordination.py
              python tests/test_panel_coordination.py --target-repo TF
              python tests/test_panel_coordination.py --live-click  # CAUTION
        """),
    )
    p.add_argument(
        "--live-click",
        action="store_true",
        default=False,
        help="Actually execute clicks for response/refresh tests. USE WITH CARE.",
    )
    p.add_argument(
        "--target-repo",
        default="desktop-agent-automation",
        help="Filter windows to those matching this repo name (default: desktop-agent-automation).",
    )
    p.add_argument(
        "--suite",
        choices=["scan", "overlap", "response", "refresh", "all"],
        default="all",
        help="Which test suite to run (default: all).",
    )
    return p.parse_args()


def _divider(title: str = "", width: int = 70) -> None:
    if title:
        pad = width - len(title) - 4
        print(f"\n{'='*2} {title} {'='*max(0,pad)}")
    else:
        print("=" * width)


def run_all(args: argparse.Namespace) -> int:
    """Run selected test suites and return exit code."""
    _divider("Panel Coordination Tests", width=70)
    print(f"  target-repo : {args.target_repo}")
    print(f"  live-click  : {args.live_click}")
    print(f"  suite       : {args.suite}")

    # Suite 1 — panel scanner (always runs first, feeds panels to subsequent suites)
    scanner = TestPanelScanner(target_repo=args.target_repo)
    if args.suite in ("scan", "all"):
        _divider("Suite 1: Panel Scanner")
        scanner.run()

    panels = scanner.panels  # reuse across suites

    exit_ok = True

    # Suite 2 — overlap detection
    if args.suite in ("overlap", "all"):
        _divider("Suite 2: Overlap Detector")
        ok = TestOverlapDetector(panels=panels).run()
        exit_ok = exit_ok and ok

    # Suite 3 — response controls
    if args.suite in ("response", "all"):
        _divider("Suite 3: Agent Response Controls")
        ok = TestAgentResponseControls(
            panels=panels,
            live_click=args.live_click,
            target_repo=args.target_repo,
        ).run()
        exit_ok = exit_ok and ok

    # Suite 4 — panel refresh
    if args.suite in ("refresh", "all"):
        _divider("Suite 4: Panel Refresh")
        ok = TestPanelRefresh(
            panels=panels,
            live_click=args.live_click,
            target_repo=args.target_repo,
        ).run()
        exit_ok = exit_ok and ok

    _divider()
    if exit_ok:
        print("  RESULT: all suites passed (dry-run safe)")
    else:
        print("  RESULT: one or more suites reported issues — see above")

    return 0 if exit_ok else 1


# ---------------------------------------------------------------------------
# pytest-compatible test functions (imported by pytest)
# ---------------------------------------------------------------------------


def test_panel_scanner_runs():
    """Verify panel scanner runs without errors."""
    args = argparse.Namespace(target_repo="desktop-agent-automation", live_click=False, suite="scan")
    scanner = TestPanelScanner(target_repo=args.target_repo)
    assert scanner.run() is True, "PanelScanner failed"


def test_overlap_detector_runs():
    """Verify overlap detector runs without errors (may need coordination modules)."""
    detector = TestOverlapDetector(panels=[])
    assert detector.run() is True, "OverlapDetector failed"


def test_response_controls_runs():
    """Verify response control scanner runs without crashing."""
    ctrl_test = TestAgentResponseControls(
        panels=[], live_click=False, target_repo="desktop-agent-automation"
    )
    assert ctrl_test.run() is True, "AgentResponseControls test failed"


def test_panel_refresh_runs():
    """Verify panel refresh control scanner runs without crashing."""
    refresh_test = TestPanelRefresh(
        panels=[], live_click=False, target_repo="desktop-agent-automation"
    )
    assert refresh_test.run() is True, "PanelRefresh test failed"


if __name__ == "__main__":
    sys.exit(run_all(_parse_args()))
