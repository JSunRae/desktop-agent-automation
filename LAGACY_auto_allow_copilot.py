import re
import time
from datetime import datetime, timedelta
import ctypes
import json
import os
import sys
import hashlib
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

# Load .env file early before any os.environ.get() calls
from dotenv import load_dotenv
load_dotenv()

# Back-compat for older import paths used by tests/tools.
# The test suite patches functions via the 'auto_allow_copilot' module name.
sys.modules.setdefault("auto_allow_copilot", sys.modules[__name__])

import keyboard
import pyvda  # For reliable virtual desktop switching by name

import uiautomation as auto
from automation.master_prompt_orchestrator import MasterPromptOrchestrator
from automation.panel_tracker import (
    get_tracker,
    on_allow_click,
    update_panel_from_window,
    process_finished_panels,
    process_rate_limited_panels,
    check_for_task_completed,
    get_window_priority,
    print_tracker_status,
    should_check_finished_panels,
    PanelStatus,
    IdleReason,
    PANEL_IDLE_THRESHOLD_MINUTES,
    PANEL_FINISHED_THRESHOLD_MINUTES,
)

# ============================================================================
# WIN32 API STRUCTURES AND CONSTANTS FOR RELIABLE HOTKEYS
# ============================================================================

# Virtual key codes
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt key
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# Modifier key states
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# Message constants
WM_HOTKEY = 0x0312

# Hotkey IDs
HOTKEY_PAUSE_ID = 1
HOTKEY_EXTRA_WAIT_ID = 2

# ============================================================================
# CONFIGURATION SECTION - Customize these values
# ============================================================================

# Timing configuration
COOLDOWN_MINUTES = 10               # wait after rate limit (10min recovery time)
POST_COOLDOWN_GRACE_MINUTES = 5     # grace period after cooldown where we ignore pre-existing rate limit indicators
EXTRA_PAUSE_SECONDS = 30            # additional wait when pause key is pressed
MIN_SCAN_INTERVAL_SECONDS = 0.5     # minimum time between scans (fast but not spinning)

# Rate-based throttling configuration
# Instead of fixed delays, we track allows in a 60-min window and throttle to stay under the limit
MAX_ALLOWS_PER_HOUR = 70            # max Allow clicks per 60-min rolling window (safe: 50-60, risky: 100+) 90 never triggered
RATE_LIMIT_BUFFER_SECONDS = 5       # extra seconds to wait after oldest event expires (safety margin)

# Rate limit avoidance notes (based on allow_metrics.jsonl analysis):
# - Safe sustained rate: ~50-60 allows/hour (~1 per minute) stays under rate limits
# - Risky: 100+ allows/hour (>1.7/min) frequently triggers rate limits
# - With 10 agents running, each agent can do ~5-6 tool calls/hour sustainably
# After clicking on a desktop, re-check it this many times (max) before switching
# Set to 0 for unlimited passes until no buttons remain
MAX_DESKTOP_RESCAN_PASSES = 0
DESKTOP_RESCAN_DELAY_SECONDS = 0.5  # delay between re-check passes on a desktop (was 0.15, increased for reliability)

# Priority desktop recheck frequency - for non-priority desktops, return to priority
# after this many rescan passes to ensure priority desktop isn't starved
# Set to 0 to disable (only return when non-priority desktop has no work)
PRIORITY_RECHECK_INTERVAL_PASSES = 5  # Return to priority desktop every N passes on non-priority desktops

# Auto-pause on typing configuration
AUTO_PAUSE_ON_TYPING = False        # disabled - was triggering false positives
TYPING_IDLE_SECONDS = 5.0           # resume after this many seconds of no typing
MOUSE_MOVEMENT_THRESHOLD = 100       # pixels - ignore mouse jiggles smaller than this
SPEAK_PAUSE_EVENTS = True           # speak pause/resume events aloud

# Hotkey configuration (these are the keys to use for manual control)
PAUSE_HOTKEY = 'ctrl+shift+p'          # hotkey to toggle pause/resume
EXTRA_WAIT_HOTKEY = 'ctrl+shift+w'     # hotkey to wait extra time

# Parse hotkeys into Win32 format for reliable detection
def _parse_hotkey_to_vk(hotkey_str: str) -> Tuple[int, int]:
    """Parse a hotkey string like 'ctrl+shift+p' into (modifiers, vk_code)."""
    parts = hotkey_str.lower().split('+')
    modifiers = 0
    vk_code = 0
    
    for part in parts:
        part = part.strip()
        if part in ('ctrl', 'control'):
            modifiers |= MOD_CONTROL
        elif part in ('shift',):
            modifiers |= MOD_SHIFT
        elif part in ('alt',):
            modifiers |= MOD_ALT
        elif part in ('win', 'windows'):
            modifiers |= MOD_WIN
        elif len(part) == 1:
            # Single character - convert to virtual key code
            vk_code = ord(part.upper())
    
    return modifiers, vk_code

# Desktop configuration
# Set to [0] or ["current"] to only check current desktop (no switching)
# Set to "auto" to automatically detect which desktops have VS Code
# Set to ["TF", "Trading"] to specify desktops BY NAME (recommended - robust to reordering)
# Set to [1, 2, 3] to manually specify desktops by number (legacy, fragile)
# NOTE: Using desktop NAMES is strongly recommended as numbers change when desktops are reordered
DESKTOPS_TO_CHECK = ["TF", "Trading"]  # Desktop names - TF first (priority), then Trading
PRIORITY_DESKTOP = "TF"                # Priority desktop name - check this first

# Desktop detection configuration (only used if DESKTOPS_TO_CHECK = "auto")
MAX_DESKTOPS_TO_SCAN = 10           # Max number of desktops to scan during auto-detection
DESKTOP_SCAN_WAIT = 2             # Seconds to wait after switching during scan (reduced for speed)

# Desktop reliability tracking - skip desktops that consistently fail
DESKTOP_MAX_CONSECUTIVE_FAILURES = 3  # Skip a desktop after this many consecutive "no windows" cycles
DESKTOP_RECHECK_AFTER_FAILURES = 5    # Re-check a failed desktop after this many cycles

# No-windows-found loop detection - warn user when stuck
NO_WINDOWS_LOOP_WARN_THRESHOLD = 10   # Warn with speech after this many consecutive "no windows found" cycles
NO_WINDOWS_LOOP_FORCE_RESYNC_AFTER = 20  # Force desktop resync after this many cycles
NO_WINDOWS_LOOP_SPEAK_INTERVAL = 30   # Seconds between repeated speech warnings

# Window priority configuration - prioritize certain windows to maximize valuable work
# Windows containing these patterns (case-insensitive) are processed first, in order
# This helps ensure high-priority agents get Allow clicks before rate limits trigger
WINDOW_PRIORITY_PATTERNS = [
    "tf",           # TF desktop/project windows - highest priority
    "trading",      # Trading desktop/project windows - second priority
]

# VS Code window title pattern
VSCODE_TITLE_SUFFIX = " - Visual Studio Code"

RATE_LIMIT_TEXT_PATTERNS = [
    "sorry, you have been rate-limited",
    "error code: rate_limited",
    "exceeded your copilot token usage",
]
RATE_LIMIT_STALE_TEXT_LENGTH = int(os.environ.get("RATE_LIMIT_STALE_TEXT_LENGTH", "800"))
RATE_LIMIT_PATTERN_MAX_OFFSET = int(os.environ.get("RATE_LIMIT_PATTERN_MAX_OFFSET", "360"))
RATE_LIMIT_PANEL_DEDUPE_MINUTES = int(os.environ.get("RATE_LIMIT_PANEL_DEDUPE_MINUTES", "180"))
RATE_LIMIT_RECENT_TEXT_WINDOW = int(os.environ.get("RATE_LIMIT_RECENT_TEXT_WINDOW", "400"))
RATE_LIMIT_SEGMENT_PREVIEW_CHARS = int(os.environ.get("RATE_LIMIT_SEGMENT_PREVIEW_CHARS", "140"))
RATE_LIMIT_SEGMENT_MAX_COUNT = int(os.environ.get("RATE_LIMIT_SEGMENT_MAX_COUNT", "3"))

# Log verbosity control - reduce console spam for routine operations
# "normal" = standard output (default), "quiet" = only important events, "verbose" = all details
LOG_VERBOSITY = os.environ.get("LOG_VERBOSITY", "normal").lower()

# Focus Terminal button deduplication - avoid spamming alerts for the same window
FOCUS_TERMINAL_DEDUPE_MINUTES = int(os.environ.get("FOCUS_TERMINAL_DEDUPE_MINUTES", "30"))
FOCUS_TERMINAL_SPEAK_ALERTS = os.environ.get("FOCUS_TERMINAL_SPEAK_ALERTS", "true").lower() == "true"

# Rate limit verification configuration
# When a suspected rate limit is detected, verify by clicking additional buttons and monitoring for activity
RATE_LIMIT_VERIFY_CLICKS = int(os.environ.get("RATE_LIMIT_VERIFY_CLICKS", "1"))  # Number of extra Allow clicks to verify (reduced for speed)
RATE_LIMIT_VERIFY_WAIT_SECONDS = float(os.environ.get("RATE_LIMIT_VERIFY_WAIT_SECONDS", "1.5"))  # Time to wait for activity after each click
RATE_LIMIT_ACTIVITY_CHECK_INTERVAL = float(os.environ.get("RATE_LIMIT_ACTIVITY_CHECK_INTERVAL", "0.3"))  # How often to check for activity

# Master agent + monitoring configuration
ENABLE_MASTER_AGENT = True
NO_ALLOW_TRIGGER_MINUTES = int(os.environ.get("NO_ALLOW_TRIGGER_MINUTES", "60"))
PROMPT_GENERATION_COOLDOWN_MINUTES = int(os.environ.get("PROMPT_GENERATION_COOLDOWN_MINUTES", "90"))
MASTER_AGENT_MODEL = os.environ.get("MASTER_AGENT_MODEL", "gpt-4o-mini")
MASTER_AGENT_MAX_DOCS = int(os.environ.get("MASTER_AGENT_MAX_DOCS", "18"))
MASTER_AGENT_MAX_CHARS = int(os.environ.get("MASTER_AGENT_MAX_CHARS", "3500"))
WSL_DOCS_ROOT = Path(
    os.environ.get(
        "MASTER_AGENT_DOCS_ROOT",
        r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\tf_1\docs",
    )
)
WSL_OPEN_TASKS_ROOT = Path(
    os.environ.get(
        "MASTER_AGENT_OPEN_TASKS_ROOT",
        str(WSL_DOCS_ROOT / "open_tasks"),
    )
)
PROMPT_OUTPUT_DIR = Path(os.environ.get("MASTER_AGENT_PROMPT_DIR", "tasks/generated_prompts"))
ALLOW_METRICS_LOG_PATH = Path(os.environ.get("ALLOW_METRICS_LOG_PATH", "automation/allow_metrics.jsonl"))
ALLOW_EVENTS_PERSIST_PATH = Path(os.environ.get("ALLOW_EVENTS_PERSIST_PATH", "automation/allow_events.json"))
ALLOW_METRICS_INTERVAL_SECONDS = int(os.environ.get("ALLOW_METRICS_INTERVAL_SECONDS", "300"))
ALLOW_EVENT_RETENTION_MINUTES = int(os.environ.get("ALLOW_EVENT_RETENTION_MINUTES", "60"))

# Global state
is_paused = False
extra_wait_until = datetime.min
last_key_time = datetime.min
is_auto_paused = False
last_allow_time = datetime.now()
allow_click_total = 0
allow_events = deque()
last_metrics_log_time = datetime.min
last_prompt_generation_time = None
prompt_orchestrator = None
has_recorded_allow = False
prompt_api_warning_emitted = False
hotkey_thread = None
hotkey_thread_running = False
last_mouse_pos = None  # Track last mouse position to detect significant movement
last_significant_input_time = datetime.min  # Track last significant input (keyboard or large mouse move)
last_cycle_metrics = {
    "total_vscode_windows": 0,
    "allow_clicked_cycle": 0,
    "keep_edits_clicked_cycle": 0,
}
rate_limit_panel_cache: Dict[str, datetime] = {}

# Session statistics tracking
session_start_time: datetime = datetime.now()
session_rate_limit_count: int = 0
session_total_allow_clicks: int = 0
session_total_keep_edits_clicks: int = 0

# Panel tracker status print interval
last_tracker_status_time: datetime = datetime.min

# Focus Terminal button alert deduplication cache
focus_terminal_alert_cache: Dict[str, datetime] = {}

# Desktop reliability tracking - track consecutive failures per desktop
desktop_failure_counts: Dict[int, int] = {}  # desktop_num -> consecutive failure count
desktop_cycles_since_check: Dict[int, int] = {}  # desktop_num -> cycles since last check

# No-windows-found loop detection state
no_windows_consecutive_count: int = 0  # Count of consecutive cycles with no windows found
last_no_windows_speech_time: datetime = datetime.min  # Last time we spoke a warning

# Zero-bounds button tracking - avoid repeatedly attempting to click invisible buttons
# Key: unique identifier for the button, Value: first seen timestamp
# Buttons in this cache will be skipped for ZERO_BOUNDS_IGNORE_MINUTES
zero_bounds_button_cache: Dict[str, datetime] = {}
ZERO_BOUNDS_IGNORE_MINUTES = 2  # Retry buttons with zero bounds after 2 minutes (reduced from 15)

# Grace period tracking - avoid re-detecting old rate limits after cooldown
grace_period_end: datetime = datetime.min  # When grace period expires
pre_cooldown_fingerprints: set = set()     # Window titles that had rate limits before cooldown

# Stale Try Again button tracking - windows with persistent unclicked Try Again buttons
# These are windows where the user never clicked Try Again and the button remains from an old rate limit
# We don't want to keep triggering cooldowns for these stale buttons
stale_try_again_windows: Dict[str, datetime] = {}  # window_fingerprint -> first_seen_time
STALE_TRY_AGAIN_IGNORE_AFTER_MINUTES = 5  # After seeing Try Again in same window this long without agent activity, consider it stale


def _log_verbose(msg: str) -> None:
    """Print message only if LOG_VERBOSITY is 'verbose'."""
    if LOG_VERBOSITY == "verbose":
        print(msg)


def _log_normal(msg: str) -> None:
    """Print message if LOG_VERBOSITY is 'normal' or 'verbose' (not 'quiet')."""
    if LOG_VERBOSITY != "quiet":
        print(msg)


def _prune_focus_terminal_cache(now: datetime | None = None) -> None:
    """Drop cached Focus Terminal alerts that fall outside the dedupe window."""
    if FOCUS_TERMINAL_DEDUPE_MINUTES <= 0:
        focus_terminal_alert_cache.clear()
        return

    now = now or datetime.now()
    cutoff = now - timedelta(minutes=FOCUS_TERMINAL_DEDUPE_MINUTES)
    for key, seen_at in list(focus_terminal_alert_cache.items()):
        if seen_at < cutoff:
            del focus_terminal_alert_cache[key]


def _should_alert_focus_terminal(window_title: str, now: datetime) -> bool:
    """Return True if we should alert for this Focus Terminal window (not recently seen)."""
    if FOCUS_TERMINAL_DEDUPE_MINUTES <= 0:
        return True  # No deduplication

    # Use window title as the key for deduplication
    key = window_title[:100]  # Truncate for consistency
    last_seen = focus_terminal_alert_cache.get(key)
    if last_seen and (now - last_seen) < timedelta(minutes=FOCUS_TERMINAL_DEDUPE_MINUTES):
        return False  # Recently alerted, skip

    focus_terminal_alert_cache[key] = now
    return True


def _prune_zero_bounds_cache(now: datetime | None = None) -> None:
    """Drop cached zero-bounds buttons that fall outside the ignore window."""
    if ZERO_BOUNDS_IGNORE_MINUTES <= 0:
        zero_bounds_button_cache.clear()
        return

    now = now or datetime.now()
    cutoff = now - timedelta(minutes=ZERO_BOUNDS_IGNORE_MINUTES)
    for key, seen_at in list(zero_bounds_button_cache.items()):
        if seen_at < cutoff:
            del zero_bounds_button_cache[key]


def _make_zero_bounds_key(window_title: str, button_name: str, control: auto.Control) -> str:
    """Create a unique key for a zero-bounds button to avoid repeated click attempts."""
    # Use window title + button name + runtime ID or automation ID if available
    runtime_key = _get_runtime_id(control)
    if runtime_key:
        return f"zb:{window_title[:50]}:{button_name}:{runtime_key}"
    
    automation_id = ""
    try:
        automation_id = getattr(control, "AutomationId", "") or ""
    except Exception:
        pass
    
    return f"zb:{window_title[:50]}:{button_name}:{automation_id}"


def _should_skip_zero_bounds_button(window_title: str, button_name: str, control: auto.Control, now: datetime) -> bool:
    """Check if this zero-bounds button should be skipped (recently seen with zero bounds)."""
    _prune_zero_bounds_cache(now)
    key = _make_zero_bounds_key(window_title, button_name, control)
    return key in zero_bounds_button_cache


def _mark_zero_bounds_button(window_title: str, button_name: str, control: auto.Control, now: datetime) -> None:
    """Mark a button as having zero bounds so we skip it for a while."""
    key = _make_zero_bounds_key(window_title, button_name, control)
    if key not in zero_bounds_button_cache:
        zero_bounds_button_cache[key] = now
        # Log to both console and file for debugging
        # Truncate window title to 40 chars for cleaner logs
        short_title = window_title[:40] if len(window_title) > 40 else window_title
        msg = f"Button '{button_name}' has zero bounds in '{short_title}' - skipping for {ZERO_BOUNDS_IGNORE_MINUTES}min"
        _log_normal(f"  ⚠ {msg}")
        # Also log to file for post-mortem analysis
        try:
            with open("@AutomationLog.txt", "a", encoding="utf-8") as f:
                f.write(f"{now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} [ZERO_BOUNDS] {msg}\n")
                # Also log the full window title for debugging
                f.write(f"    Full title: {window_title}\n")
        except Exception:
            pass


def _has_valid_bounds(control: auto.Control) -> bool:
    """Check if a control has valid (non-zero) bounding rectangle."""
    try:
        rect = control.BoundingRectangle
        # Check for zero bounds
        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            return False
        # Check for non-positive size
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return False
        return True
    except Exception:
        return False


def _try_scroll_and_check_bounds(control: auto.Control, vs_win: auto.Control | None = None) -> bool:
    """
    Attempt to scroll a control into view and return True if it now has valid bounds.
    
    This helps with virtualized controls (like buttons in scrolled chat panels) that
    report zero bounds because they're not currently rendered.
    
    Args:
        control: The control to scroll into view
        vs_win: Optional parent VS Code window for chat-level scrolling
    
    Returns:
        True if control now has valid bounds, False otherwise
    """
    # First, try the control's own ScrollItem pattern
    if _scroll_control_into_view(control):
        time.sleep(0.1)
        if _has_valid_bounds(control):
            return True
    
    # If we have the VS Code window, try scrolling the chat to bottom
    if vs_win is not None:
        try:
            scroll_chat_to_bottom(vs_win)
            time.sleep(0.15)
            if _has_valid_bounds(control):
                return True
        except Exception:
            pass
    
    # Last resort: Try to focus the control and send scroll keys
    try:
        # Try Page Down and End keys to scroll into view
        parent = control.GetParentControl()
        if parent:
            parent.SetFocus()
            time.sleep(0.05)
            auto.SendKeys('{End}')
            time.sleep(0.1)
            if _has_valid_bounds(control):
                return True
            auto.SendKeys('{Ctrl}{End}')
            time.sleep(0.1)
            if _has_valid_bounds(control):
                return True
    except Exception:
        pass
    
    return False


def _should_skip_desktop(desktop_num: int) -> bool:
    """Check if a desktop should be skipped due to consecutive failures."""
    if DESKTOP_MAX_CONSECUTIVE_FAILURES <= 0:
        return False  # Tracking disabled

    failures = desktop_failure_counts.get(desktop_num, 0)
    if failures >= DESKTOP_MAX_CONSECUTIVE_FAILURES:
        # Check if it's time to re-check this desktop
        cycles_since = desktop_cycles_since_check.get(desktop_num, 0)
        if cycles_since >= DESKTOP_RECHECK_AFTER_FAILURES:
            # Time to re-check
            return False
        return True
    return False


def _record_desktop_result(desktop_num: int, found_windows: bool) -> None:
    """Record whether we found windows on a desktop (for reliability tracking)."""
    if found_windows:
        # Reset failure count on success
        desktop_failure_counts[desktop_num] = 0
        desktop_cycles_since_check[desktop_num] = 0
    else:
        # Increment failure count
        desktop_failure_counts[desktop_num] = desktop_failure_counts.get(desktop_num, 0) + 1
        desktop_cycles_since_check[desktop_num] = 0


def _increment_desktop_cycles() -> None:
    """Increment cycles counter for all tracked desktops."""
    for desktop_num in list(desktop_cycles_since_check.keys()):
        desktop_cycles_since_check[desktop_num] = desktop_cycles_since_check.get(desktop_num, 0) + 1


def _reset_all_desktop_failures() -> None:
    """Reset all desktop failure counters to force re-checking all desktops."""
    global desktop_failure_counts, desktop_cycles_since_check
    desktop_failure_counts.clear()
    desktop_cycles_since_check.clear()
    print(f"[{datetime.now()}] 🔄 Reset all desktop failure counters - will recheck all desktops")


def _handle_no_windows_loop(now: datetime) -> bool:
    """
    Check if we're stuck in a no-windows-found loop and handle it.
    
    Returns True if we should force a desktop resync.
    """
    global no_windows_consecutive_count, last_no_windows_speech_time, _desktop_sync_done
    
    no_windows_consecutive_count += 1
    
    # Check if we've been stuck for a while
    if no_windows_consecutive_count >= NO_WINDOWS_LOOP_WARN_THRESHOLD:
        # Check if it's time for a speech warning
        time_since_last_speech = (now - last_no_windows_speech_time).total_seconds()
        
        if time_since_last_speech >= NO_WINDOWS_LOOP_SPEAK_INTERVAL:
            last_no_windows_speech_time = now
            
            # Play alert beep
            _beep(600, 300)
            _beep(400, 300)
            
            # Speak warning
            msg = f"Warning: No VS Code windows found for {no_windows_consecutive_count} cycles. All desktops being skipped."
            print(f"\n{'='*70}")
            print(f"[{now}] ⚠️ {msg}")
            print(f"{'='*70}\n")
            _speak("Warning. No VS Code windows found. All desktops are being skipped. Check your virtual desktops.")
            _flash_console()
    
    # Force resync after extended time stuck
    if no_windows_consecutive_count >= NO_WINDOWS_LOOP_FORCE_RESYNC_AFTER:
        print(f"\n[{now}] 🔄 Force-resyncing desktops after {no_windows_consecutive_count} failed cycles...")
        _reset_all_desktop_failures()
        _desktop_sync_done = False  # Force re-sync of desktop position
        no_windows_consecutive_count = 0  # Reset counter
        return True
    
    return False


def _reset_no_windows_loop_counter() -> None:
    """Reset the no-windows loop counter when we find windows."""
    global no_windows_consecutive_count
    if no_windows_consecutive_count > 0:
        no_windows_consecutive_count = 0


def _beep(frequency: int = 800, duration: int = 100):
    """Play a short beep sound for audio feedback."""
    try:
        ctypes.windll.kernel32.Beep(frequency, duration)
    except Exception:
        pass


def _speak(text: str):
    """Use Windows text-to-speech to speak a message."""
    try:
        import subprocess
        # Use PowerShell's built-in speech synthesis with English voice
        ps_script = f'''
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like "en-*" }}
if ($voices.Count -gt 0) {{
    $synth.SelectVoice($voices[0].VoiceInfo.Name)
}}
$synth.Speak("{text}")
'''
        subprocess.Popen(
            ["powershell", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as e:
        print(f"  ⚠ TTS failed: {e}")


def _flash_console():
    """Flash the console window to get user's attention."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.FlashWindow(hwnd, True)
    except Exception:
        pass


def _get_window_priority(window: auto.Control) -> int:
    """
    Return a priority score for a VS Code window based on its title and panel status.
    Lower numbers = higher priority (processed first).
    
    Priority layers:
    1. Panel status (live panels first, finished panels last)
    2. Title patterns (WINDOW_PRIORITY_PATTERNS)
    """
    try:
        title = (window.Name or "")
        
        # First priority layer: Panel status
        # Live panels get priority 0-99, Idle get 100-199, Finished get 200-299
        panel_priority = get_window_priority(title) * 100
        
        # Second priority layer: Title pattern matching
        title_lower = title.lower()
        for priority_idx, pattern in enumerate(WINDOW_PRIORITY_PATTERNS):
            if pattern.lower() in title_lower:
                return panel_priority + priority_idx
        
        return panel_priority + len(WINDOW_PRIORITY_PATTERNS)
    except Exception:
        return len(WINDOW_PRIORITY_PATTERNS)


def _sort_windows_by_priority(windows: list) -> list:
    """
    Sort VS Code windows by priority based on WINDOW_PRIORITY_PATTERNS.
    TF windows first, then Trading, then others.
    """
    if not WINDOW_PRIORITY_PATTERNS:
        return windows
    return sorted(windows, key=_get_window_priority)
 

def _earliest_rate_limit_match(normalized_text: str) -> int | None:
    """Return the earliest index of any rate-limit pattern in the provided text."""
    indices = [normalized_text.find(pattern) for pattern in RATE_LIMIT_TEXT_PATTERNS]
    indices = [idx for idx in indices if idx != -1]
    if not indices:
        return None
    return min(indices)


def _is_stale_rate_limit_text(normalized_text: str, match_index: int) -> bool:
    """Heuristically determine if the match likely comes from historical chat text."""
    if RATE_LIMIT_STALE_TEXT_LENGTH <= 0:
        return False
    text_length = len(normalized_text)
    if text_length <= RATE_LIMIT_STALE_TEXT_LENGTH:
        return False
    if RATE_LIMIT_RECENT_TEXT_WINDOW > 0 and match_index >= max(0, text_length - RATE_LIMIT_RECENT_TEXT_WINDOW):
        return False
    return match_index > RATE_LIMIT_PATTERN_MAX_OFFSET


def _recent_text_window(text: str) -> tuple[str, int]:
    """Return the trailing window of text plus its start index within the original string."""
    window = RATE_LIMIT_RECENT_TEXT_WINDOW
    if window <= 0 or len(text) <= window:
        return text, 0
    start = len(text) - window
    return text[start:], start


def _segment_recent_text(text: str) -> List[str]:
    """Return human-friendly previews of the latest segments inside the recent text window."""
    text = text.strip()
    if not text:
        return []

    splitter = re.compile(r"(?:\r?\n){2,}|(?:\r?\n\s*[-=*]{3,}\s*\r?\n)")
    parts = [chunk.strip() for chunk in splitter.split(text) if chunk.strip()]
    if not parts:
        parts = [chunk.strip() for chunk in text.splitlines() if chunk.strip()]

    if not parts:
        return []

    selected = parts[-RATE_LIMIT_SEGMENT_MAX_COUNT :]
    previews: List[str] = []
    for segment in selected:
        preview = segment[:RATE_LIMIT_SEGMENT_PREVIEW_CHARS]
        if len(segment) > RATE_LIMIT_SEGMENT_PREVIEW_CHARS:
            preview += "…"
        previews.append(preview)
    return previews


def _get_runtime_id(panel: auto.Control) -> str | None:
    """Safely extract the runtime identifier for a UI Automation control."""
    try:
        getter = getattr(panel, "GetRuntimeId", None)
        if callable(getter):
            runtime_id = getter()
            if runtime_id and hasattr(runtime_id, "__iter__"):
                runtime_iterable = cast(Iterable[Any], runtime_id)
                runtime_parts = [str(part) for part in runtime_iterable]
                if runtime_parts:
                    return ",".join(runtime_parts)
    except Exception:
        pass

    try:
        runtime_id = getattr(panel, "RuntimeId", None)
        if runtime_id and hasattr(runtime_id, "__iter__"):
            runtime_iterable = cast(Iterable[Any], runtime_id)
            runtime_parts = [str(part) for part in runtime_iterable]
            if runtime_parts:
                return ",".join(runtime_parts)
    except Exception:
        pass
    return None


def _rate_limit_panel_identifier(panel: auto.Control, window_label: str, normalized_text: str) -> str:
    """Generate a stable identifier for a panel to suppress repeated detections."""
    runtime_key = _get_runtime_id(panel)
    if runtime_key:
        return f"rid:{window_label}:{runtime_key}"

    automation_id = ""
    try:
        automation_id = getattr(panel, "AutomationId", "") or ""
    except Exception:
        automation_id = ""

    bounds = "unknown"
    try:
        rect = panel.BoundingRectangle
        bounds = f"{rect.left}:{rect.top}:{rect.right}:{rect.bottom}"
    except Exception:
        pass

    recent_text, _ = _recent_text_window(normalized_text)
    snippet = recent_text[-160:]
    snippet_hash = hashlib.sha1(snippet.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"txt:{window_label}:{automation_id}:{bounds}:{snippet_hash}"


def _prune_rate_limit_panel_cache(now: datetime | None = None) -> None:
    """Drop cached panel identifiers that fall outside the dedupe window."""
    if RATE_LIMIT_PANEL_DEDUPE_MINUTES <= 0:
        rate_limit_panel_cache.clear()
        return

    now = now or datetime.now()
    cutoff = now - timedelta(minutes=RATE_LIMIT_PANEL_DEDUPE_MINUTES)
    for key, seen_at in list(rate_limit_panel_cache.items()):
        if seen_at < cutoff:
            del rate_limit_panel_cache[key]


def _mark_rate_limit_panel_seen(panel_key: str, now: datetime) -> bool:
    """Return True if the panel is new (and mark it); False when already seen recently."""
    if RATE_LIMIT_PANEL_DEDUPE_MINUTES <= 0:
        return True

    last_seen = rate_limit_panel_cache.get(panel_key)
    if last_seen and (now - last_seen) < timedelta(minutes=RATE_LIMIT_PANEL_DEDUPE_MINUTES):
        return False

    rate_limit_panel_cache[panel_key] = now
    return True


def toggle_pause():
    """Toggle pause state when hotkey is pressed."""
    global is_paused, is_auto_paused
    is_paused = not is_paused
    if is_paused:
        is_auto_paused = False  # Clear auto-pause when manually paused
        _beep(600, 200)  # Low tone for pause
        if SPEAK_PAUSE_EVENTS:
            _speak("Paused")
    else:
        _beep(1000, 100)  # High tone for resume
        _beep(1200, 100)
        if SPEAK_PAUSE_EVENTS:
            _speak("Resumed")
    _flash_console()
    state = "PAUSED" if is_paused else "RESUMED"
    print(f"\n{'='*50}")
    print(f"[{datetime.now()}] *** MANUAL {state} ***")
    print(f"{'='*50}\n")


def trigger_extra_wait():
    """Add extra wait time when hotkey is pressed."""
    global extra_wait_until
    extra_wait_until = datetime.now() + timedelta(seconds=EXTRA_PAUSE_SECONDS)
    _beep(800, 100)
    _beep(800, 100)
    _flash_console()
    print(f"\n[{datetime.now()}] *** EXTRA WAIT: {EXTRA_PAUSE_SECONDS}s ***\n")


def on_key_event(event):
    """
    Callback for keyboard events. Updates last_key_time when typing detected.
    This enables auto-pause when user is actively typing.
    """
    global last_key_time

    if AUTO_PAUSE_ON_TYPING:
        last_key_time = datetime.now()


# ============================================================================
# RELIABLE HOTKEY DETECTION USING WIN32 API
# ============================================================================

def _get_async_key_state(vk_code: int) -> bool:
    """Check if a key is currently pressed using GetAsyncKeyState."""
    state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
    # High bit set means key is currently pressed
    return (state & 0x8000) != 0


def _check_modifier_pressed(modifier: int) -> bool:
    """Check if a modifier combination is currently pressed."""
    if modifier & MOD_CONTROL:
        if not (_get_async_key_state(VK_CONTROL) or _get_async_key_state(0xA2) or _get_async_key_state(0xA3)):
            return False
    if modifier & MOD_SHIFT:
        if not (_get_async_key_state(VK_SHIFT) or _get_async_key_state(0xA0) or _get_async_key_state(0xA1)):
            return False
    if modifier & MOD_ALT:
        if not (_get_async_key_state(VK_MENU) or _get_async_key_state(0xA4) or _get_async_key_state(0xA5)):
            return False
    if modifier & MOD_WIN:
        if not (_get_async_key_state(VK_LWIN) or _get_async_key_state(VK_RWIN)):
            return False
    return True


class HotkeyState:
    """Track hotkey state to prevent repeated triggers."""
    def __init__(self):
        self.pause_was_pressed = False
        self.extra_wait_was_pressed = False
        self.last_pause_trigger = datetime.min
        self.last_extra_wait_trigger = datetime.min
        self.debounce_seconds = 0.5  # Prevent re-trigger for this long


hotkey_state = HotkeyState()

# Pre-parse hotkeys at module load time for performance (avoid re-parsing every poll)
_CACHED_PAUSE_HOTKEY = _parse_hotkey_to_vk(PAUSE_HOTKEY)
_CACHED_EXTRA_WAIT_HOTKEY = _parse_hotkey_to_vk(EXTRA_WAIT_HOTKEY)


def check_hotkeys_polled():
    """
    Check for hotkeys using polling (GetAsyncKeyState).
    This is more reliable than keyboard library hooks on Windows.
    Call this frequently from the main loop.
    """
    global hotkey_state
    
    now = datetime.now()
    
    # Use pre-parsed hotkeys for performance
    pause_mods, pause_vk = _CACHED_PAUSE_HOTKEY
    extra_mods, extra_vk = _CACHED_EXTRA_WAIT_HOTKEY
    
    # Check pause hotkey (ctrl+shift+p)
    pause_pressed = _check_modifier_pressed(pause_mods) and _get_async_key_state(pause_vk)
    
    if pause_pressed and not hotkey_state.pause_was_pressed:
        # Key just pressed (rising edge)
        if (now - hotkey_state.last_pause_trigger).total_seconds() > hotkey_state.debounce_seconds:
            hotkey_state.last_pause_trigger = now
            toggle_pause()
    hotkey_state.pause_was_pressed = pause_pressed
    
    # Check extra wait hotkey (ctrl+shift+w)
    extra_pressed = _check_modifier_pressed(extra_mods) and _get_async_key_state(extra_vk)
    
    if extra_pressed and not hotkey_state.extra_wait_was_pressed:
        # Key just pressed (rising edge)
        if (now - hotkey_state.last_extra_wait_trigger).total_seconds() > hotkey_state.debounce_seconds:
            hotkey_state.last_extra_wait_trigger = now
            trigger_extra_wait()
    hotkey_state.extra_wait_was_pressed = extra_pressed


def _load_allow_events() -> None:
    """Load persisted allow events from disk on startup."""
    global allow_events, last_allow_time, allow_click_total, has_recorded_allow
    
    if not ALLOW_EVENTS_PERSIST_PATH.exists():
        return
    
    try:
        with ALLOW_EVENTS_PERSIST_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        now = datetime.now()
        cutoff = now - timedelta(minutes=ALLOW_EVENT_RETENTION_MINUTES)
        loaded_count = 0
        
        for event in data.get("events", []):
            try:
                event_time = datetime.fromisoformat(event["timestamp"])
                if event_time > cutoff:  # Only load events still within the retention window
                    allow_events.append((event_time, event.get("window", "Unknown")))
                    loaded_count += 1
            except (ValueError, KeyError):
                continue
        
        if loaded_count > 0:
            # Update last_allow_time to the most recent loaded event
            last_allow_time = allow_events[-1][0]
            has_recorded_allow = True
            print(f"[{now}] Loaded {loaded_count} allow events from previous session ({len(allow_events)}/{MAX_ALLOWS_PER_HOUR} in last 60min)")
    except Exception as e:
        print(f"[{datetime.now()}] Warning: Could not load persisted allow events: {e}")


def _save_allow_events() -> None:
    """Save current allow events to disk for persistence across restarts."""
    try:
        ALLOW_EVENTS_PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        events_data = {
            "saved_at": datetime.now().isoformat(),
            "retention_minutes": ALLOW_EVENT_RETENTION_MINUTES,
            "events": [
                {"timestamp": ts.isoformat(), "window": title}
                for ts, title in allow_events
            ]
        }
        
        with ALLOW_EVENTS_PERSIST_PATH.open("w", encoding="utf-8") as f:
            json.dump(events_data, f, indent=2)
    except Exception as e:
        print(f"[{datetime.now()}] Warning: Could not save allow events: {e}")


def prune_allow_events(reference_time=None) -> None:
    """Drop allow-click records that fall outside the retention window."""
    reference_time = reference_time or datetime.now()
    cutoff = reference_time - timedelta(minutes=ALLOW_EVENT_RETENTION_MINUTES)
    while allow_events and allow_events[0][0] < cutoff:
        allow_events.popleft()


def get_rate_limit_wait_seconds(now: datetime | None = None) -> float:
    """
    Calculate how long to wait before the next Allow click is permitted.
    
    Returns 0 if we're under the rate limit and can click immediately.
    Returns positive seconds if we need to wait for the oldest event to expire.
    """
    now = now or datetime.now()
    prune_allow_events(now)
    
    current_count = len(allow_events)
    
    if current_count < MAX_ALLOWS_PER_HOUR:
        return 0.0  # Under limit, can click immediately
    
    # At or over limit - calculate when the oldest event will expire
    if not allow_events:
        return 0.0  # Shouldn't happen, but safety check
    
    oldest_event_time = allow_events[0][0]
    expiry_time = oldest_event_time + timedelta(minutes=ALLOW_EVENT_RETENTION_MINUTES)
    wait_seconds = (expiry_time - now).total_seconds() + RATE_LIMIT_BUFFER_SECONDS
    
    return max(0.0, wait_seconds)


def can_click_allow(now: datetime | None = None) -> bool:
    """Return True if we're under the rate limit and can click Allow buttons."""
    return get_rate_limit_wait_seconds(now) <= 0


def _format_rate_status(now: datetime | None = None) -> str:
    """Return a human-readable rate limit status string."""
    now = now or datetime.now()
    prune_allow_events(now)
    current_count = len(allow_events)
    return f"{current_count}/{MAX_ALLOWS_PER_HOUR} allows in last 60min"


def record_allow_click(window_title: str) -> None:
    """Store the timestamp + panel name for an Allow action."""
    global last_allow_time, allow_click_total, has_recorded_allow
    now = datetime.now()
    allow_events.append((now, window_title or "Unknown"))
    last_allow_time = now
    allow_click_total += 1
    has_recorded_allow = True
    prune_allow_events(now)
    _save_allow_events()  # Persist to disk for restart survival
    
    # Track panel for idle/finished monitoring
    on_allow_click(window_title)


def _allow_metrics_snapshot(now: datetime) -> dict:
    prune_allow_events(now)
    panels = {title for _, title in allow_events}
    return {
        "allows_last_window": len(allow_events),
        "panels_last_window": len(panels),
        "last_allow_time": last_allow_time.isoformat() if allow_events else None,
    }


def log_allow_metrics(
    now: datetime,
    *,
    total_vscode_windows: int,
    allow_clicked_cycle: int,
    keep_edits_clicked_cycle: int,
    force: bool = False,
) -> None:
    """Persist allow-click stats for future rate-limit tuning."""
    global last_metrics_log_time
    if not force and (now - last_metrics_log_time).total_seconds() < ALLOW_METRICS_INTERVAL_SECONDS:
        return

    metrics = _allow_metrics_snapshot(now)
    record = {
        "timestamp": now.isoformat(),
        "allows_last_window": metrics["allows_last_window"],
        "panels_last_window": metrics["panels_last_window"],
        "last_allow_time": metrics["last_allow_time"],
        "total_allow_clicks": allow_click_total,
        "allow_clicked_this_cycle": allow_clicked_cycle,
        "keep_edits_clicked_this_cycle": keep_edits_clicked_cycle,
        "total_vscode_windows_seen": total_vscode_windows,
        "max_allows_per_hour": MAX_ALLOWS_PER_HOUR,
        "retention_minutes": ALLOW_EVENT_RETENTION_MINUTES,
    }
    ALLOW_METRICS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ALLOW_METRICS_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    last_metrics_log_time = now


def should_trigger_master_agent(now: datetime) -> bool:
    """Return True when we should generate master prompts."""
    global prompt_api_warning_emitted

    if not ENABLE_MASTER_AGENT:
        return False
    if not has_recorded_allow:
        return False
    if (now - last_allow_time).total_seconds() < NO_ALLOW_TRIGGER_MINUTES * 60:
        return False
    if (
        last_prompt_generation_time
        and (now - last_prompt_generation_time).total_seconds()
        < PROMPT_GENERATION_COOLDOWN_MINUTES * 60
    ):
        return False
    if not os.environ.get("OPENAI_API_KEY"):
        if not prompt_api_warning_emitted:
            print(
                f"[{now}] Cannot generate master prompts because OPENAI_API_KEY is not configured."
            )
            prompt_api_warning_emitted = True
        return False
    return True


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def print_session_summary() -> None:
    """Print a summary of session statistics."""
    now = datetime.now()
    uptime = (now - session_start_time).total_seconds()
    
    print(f"\n{'='*60}")
    print("SESSION SUMMARY")
    print(f"{'='*60}")
    print(f"  Started:           {session_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Ended:             {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Uptime:            {_format_duration(uptime)}")
    print(f"  Allow clicks:      {session_total_allow_clicks}")
    print(f"  Keep Edits clicks: {session_total_keep_edits_clicks}")
    print(f"  Rate limits hit:   {session_rate_limit_count}")
    if session_rate_limit_count > 0 and uptime > 0:
        avg_minutes = uptime / 60 / max(session_rate_limit_count, 1)
        print(f"  Avg time between:  {avg_minutes:.1f} minutes per rate limit")
    print(f"{'='*60}\n")


def flush_metrics_on_exit(reason: str = "shutdown") -> None:
    """Force a final metrics log when the script terminates."""
    global last_cycle_metrics
    snapshot = last_cycle_metrics.copy()
    now = datetime.now()
    
    # Print session summary first
    print_session_summary()
    
    try:
        log_allow_metrics(
            now,
            total_vscode_windows=snapshot.get("total_vscode_windows", 0),
            allow_clicked_cycle=snapshot.get("allow_clicked_cycle", 0),
            keep_edits_clicked_cycle=snapshot.get("keep_edits_clicked_cycle", 0),
            force=True,
        )
        print(
            f"[{now}] Saved final allow metrics before {reason}. "
            f"Windows={snapshot.get('total_vscode_windows', 0)}, "
            f"Allow={snapshot.get('allow_clicked_cycle', 0)}, "
            f"KeepEdits={snapshot.get('keep_edits_clicked_cycle', 0)}"
        )
    except Exception as exc:
        print(f"[{datetime.now()}] Warning: failed to flush metrics on {reason}: {exc}")


def trigger_master_agent_prompt_generation(now: datetime) -> None:
    """Kick off the document upload + prompt generation workflow."""
    global prompt_orchestrator, last_prompt_generation_time
    docs_dirs = [WSL_DOCS_ROOT]
    if WSL_OPEN_TASKS_ROOT != WSL_DOCS_ROOT:
        docs_dirs.append(WSL_OPEN_TASKS_ROOT)

    try:
        if prompt_orchestrator is None:
            prompt_orchestrator = MasterPromptOrchestrator(
                docs_dirs=docs_dirs,
                output_dir=PROMPT_OUTPUT_DIR,
                max_docs=MASTER_AGENT_MAX_DOCS,
                max_chars=MASTER_AGENT_MAX_CHARS,
                model=MASTER_AGENT_MODEL,
                logger=lambda msg: print(f"[{datetime.now()}] [MASTER] {msg}"),
            )

        print(
            f"[{now}] No Allow button clicked for {NO_ALLOW_TRIGGER_MINUTES} minutes. "
            "Generating master prompt batch..."
        )
        result = prompt_orchestrator.generate_prompt_batch()
        if result and result.output_path:
            print(f"[{datetime.now()}] Prompts saved to {result.output_path}")
        else:
            print(f"[{datetime.now()}] Prompt generation completed without output.")
    except Exception as exc:
        print(f"[{datetime.now()}] Master prompt generation failed: {exc}")
    finally:
        last_prompt_generation_time = now


# Track current desktop for optimized switching
_current_desktop = 1  # Assume we start on desktop 1 (will sync on first switch)
_desktop_sync_done = False  # Have we synced to a known position?

# ============================================================================
# WINDOW HANDLE CACHING - Skip desktop switching after initial scan
# ============================================================================

# Global cache of discovered VS Code window handles
# Key: window handle (HWND), Value: (window_title, last_seen_time, desktop_id)
# desktop_id can be a name (str) or number (int)
_cached_window_handles: Dict[int, Tuple[str, datetime, str]] = {}
_cache_initialized = False
_last_cache_refresh: datetime = datetime.min
CACHE_REFRESH_INTERVAL_MINUTES = 5  # Refresh cache every 5 minutes to find new windows
CACHE_STALE_THRESHOLD_MINUTES = 10  # Remove windows not seen for this long

# Feature toggle: Use cached handles instead of switching desktops
# Set to True to skip desktop switching after initial scan (recommended)
USE_CACHED_HANDLES = True


def _needs_desktop_switch(desktop_id: int | str) -> bool:
    """Check if a desktop_id requires switching (i.e., not 'current desktop')."""
    return desktop_id != 0 and desktop_id != "current"


def _prune_stale_cached_handles(now: datetime | None = None) -> None:
    """Remove cached window handles that haven't been seen recently."""
    now = now or datetime.now()
    stale_cutoff = now - timedelta(minutes=CACHE_STALE_THRESHOLD_MINUTES)
    
    stale_keys = [
        hwnd for hwnd, (_, last_seen, _) in _cached_window_handles.items()
        if last_seen < stale_cutoff
    ]
    
    for hwnd in stale_keys:
        title, _, desktop = _cached_window_handles.pop(hwnd, ("", datetime.min, 0))
        _log_verbose(f"  [CACHE] Removed stale handle: {title[:40]}... (desktop {desktop})")


def _refresh_window_cache(desktops: List[int | str], force: bool = False) -> int:
    """
    Scan all configured desktops and cache window handles.
    
    This is the ONE time we switch between desktops - to discover all windows.
    After this, we use the cached handles directly.
    
    Args:
        desktops: List of desktop identifiers - can be numbers (int) or names (str)
        force: If True, scan even if cache was recently refreshed
        
    Returns:
        Number of windows cached
    """
    global _cached_window_handles, _cache_initialized, _last_cache_refresh
    
    now = datetime.now()
    
    # Skip if recently refreshed (unless forced)
    if not force and _cache_initialized:
        mins_since_refresh = (now - _last_cache_refresh).total_seconds() / 60
        if mins_since_refresh < CACHE_REFRESH_INTERVAL_MINUTES:
            return len(_cached_window_handles)
    
    print(f"\n[{now}] 📋 Scanning desktops to cache window handles...")
    
    # Prune stale entries first
    _prune_stale_cached_handles(now)
    
    new_windows = 0
    updated_windows = 0
    
    for desktop_id in desktops:
        # Check if this is "current desktop" (no switch needed)
        if desktop_id == 0 or desktop_id == "current":
            desktop_label = "current"
            vscode_windows = find_all_vscode_windows(timeout=0.5)
        else:
            # Switch to desktop and scan
            desktop_label = str(desktop_id)
            switch_to_desktop(desktop_id)
            time.sleep(0.5)  # Wait for UI to stabilize (pyvda is faster)
            vscode_windows = find_all_vscode_windows(timeout=0.5)
        
        for vs_win in vscode_windows:
            try:
                hwnd = vs_win.NativeWindowHandle
                title = vs_win.Name or "Unknown"
                
                if hwnd:
                    if hwnd in _cached_window_handles:
                        # Update existing entry
                        _cached_window_handles[hwnd] = (title, now, desktop_label)
                        updated_windows += 1
                    else:
                        # New window
                        _cached_window_handles[hwnd] = (title, now, desktop_label)
                        new_windows += 1
                        _log_verbose(f"  [CACHE] Found: {title[:50]}... ({desktop_label})")
            except Exception:
                continue
    
    _cache_initialized = True
    _last_cache_refresh = now
    
    total = len(_cached_window_handles)
    print(f"[{now}] ✓ Cache: {total} window(s) ({new_windows} new, {updated_windows} updated)")
    
    return total


def get_cached_vscode_windows() -> List[auto.Control]:
    """
    Get VS Code windows from cache without switching desktops.
    
    Uses ControlFromHandle to get fresh Control objects from cached handles.
    Windows that no longer exist are automatically removed from cache.
    
    Returns:
        List of VS Code window controls
    """
    now = datetime.now()
    windows = []
    invalid_handles = []
    
    for hwnd, (title, last_seen, desktop) in list(_cached_window_handles.items()):
        try:
            # Get control from handle - this works across virtual desktops!
            ctrl = auto.ControlFromHandle(hwnd)
            
            if ctrl and ctrl.Exists(0.2):
                # Verify it's still a VS Code window
                name = ctrl.Name or ""
                if name.endswith(VSCODE_TITLE_SUFFIX):
                    windows.append(ctrl)
                    # Update last seen time
                    _cached_window_handles[hwnd] = (name, now, desktop)
                else:
                    # Window changed (no longer VS Code)
                    invalid_handles.append(hwnd)
            else:
                # Window no longer exists
                invalid_handles.append(hwnd)
        except Exception:
            # Handle invalid
            invalid_handles.append(hwnd)
    
    # Remove invalid handles
    for hwnd in invalid_handles:
        if hwnd in _cached_window_handles:
            title, _, desktop = _cached_window_handles.pop(hwnd)
            _log_verbose(f"  [CACHE] Removed invalid: {title[:40]}...")
    
    return windows


def should_refresh_cache(now: datetime | None = None) -> bool:
    """Check if the window cache should be refreshed."""
    global _cache_initialized, _last_cache_refresh
    
    if not _cache_initialized:
        return True
    
    now = now or datetime.now()
    mins_since_refresh = (now - _last_cache_refresh).total_seconds() / 60
    return mins_since_refresh >= CACHE_REFRESH_INTERVAL_MINUTES


# Cache of pyvda desktop objects by name for fast lookup
_pyvda_desktop_cache: Dict[str, Any] = {}
_pyvda_cache_time: datetime = datetime.min


def _get_desktop_by_name(name: str) -> Optional[Any]:
    """Get a pyvda VirtualDesktop object by name. Uses cache for performance."""
    global _pyvda_desktop_cache, _pyvda_cache_time
    
    now = datetime.now()
    # Refresh cache every 60 seconds or if empty
    if not _pyvda_desktop_cache or (now - _pyvda_cache_time).total_seconds() > 60:
        try:
            _pyvda_desktop_cache = {}
            for desktop in pyvda.get_virtual_desktops():
                _pyvda_desktop_cache[desktop.name] = desktop
            _pyvda_cache_time = now
        except Exception as e:
            print(f"[{now}] Warning: Failed to refresh pyvda desktop cache: {e}")
            return None
    
    return _pyvda_desktop_cache.get(name)


def _get_current_desktop_name() -> Optional[str]:
    """Get the name of the current virtual desktop."""
    try:
        current = pyvda.VirtualDesktop.current()
        return current.name if current else None
    except Exception:
        return None


def switch_to_desktop(desktop_id: int | str, force_sync: bool = False):
    """
    Switch to a specific virtual desktop (Windows 10/11).
    
    Args:
        desktop_id: Either a desktop NAME (str) like "TF" or "Trading", 
                   or a desktop NUMBER (int) for legacy compatibility.
                   Use 0 or "current" to stay on current desktop.
        force_sync: Ignored when using pyvda (always reliable)
    
    Uses pyvda for reliable direct switching by name (recommended).
    Falls back to keyboard navigation for numeric desktop IDs.
    """
    global _current_desktop, _desktop_sync_done
    
    # Handle "current desktop" case
    if desktop_id == 0 or desktop_id == "current":
        return
    
    try:
        # If desktop_id is a string (name), use pyvda for reliable switching
        if isinstance(desktop_id, str):
            target_desktop = _get_desktop_by_name(desktop_id)
            if target_desktop is None:
                print(f"[{datetime.now()}] ⚠ Desktop '{desktop_id}' not found. Available desktops:")
                try:
                    for d in pyvda.get_virtual_desktops():
                        print(f"    - {d.name}")
                except Exception:
                    pass
                return
            
            # Check if already on target desktop
            current_name = _get_current_desktop_name()
            if current_name == desktop_id:
                return  # Already there
            
            # Switch using pyvda - this is reliable and instant!
            target_desktop.go()
            time.sleep(0.3)  # Brief wait for UI to update
            
            # Update tracking (for compatibility)
            try:
                _current_desktop = target_desktop.number
                _desktop_sync_done = True
            except Exception:
                pass
            
            return
        
        # Legacy: numeric desktop_id - use keyboard navigation
        desktop_number = int(desktop_id)
        
        # Release any held modifier keys first to avoid interference
        keyboard.release('ctrl')
        keyboard.release('shift')
        keyboard.release('alt')
        keyboard.release('win')
        time.sleep(0.15)  # Brief wait after key release
        
        # If we don't know where we are, sync to desktop 1 first (one-time)
        if not _desktop_sync_done or force_sync:
            _log_verbose("  📍 Syncing desktop position (going to desktop 1)...")
            for i in range(MAX_DESKTOPS_TO_SCAN):
                keyboard.send('win+ctrl+left')
                time.sleep(0.15)
            _current_desktop = 1
            _desktop_sync_done = True
            time.sleep(0.8)  # Longer wait after sync
        
        # If already on target, no switch needed
        if _current_desktop == desktop_number:
            return
        
        # Calculate direction and steps needed
        if desktop_number > _current_desktop:
            # Move right
            steps = desktop_number - _current_desktop
            for i in range(steps):
                keyboard.send('win+ctrl+right')
                time.sleep(0.2)  # Increased delay between steps
        elif desktop_number < _current_desktop:
            # Move left
            steps = _current_desktop - desktop_number
            for i in range(steps):
                keyboard.send('win+ctrl+left')
                time.sleep(0.2)  # Increased delay between steps
        
        _current_desktop = desktop_number
        
        # Wait for UI tree to update after switch
        time.sleep(1.5)  # Longer wait for UI tree updates
        
        # IMPORTANT: After switching, try to activate a window on this desktop
        # to ensure the UI tree is properly rendered
        try:
            windows = find_all_vscode_windows(timeout=0.3)
            if windows:
                # Activate the first window to force UI rendering
                first_win = windows[0]
                try:
                    first_win.SetActive()
                    time.sleep(0.2)
                    hwnd = first_win.NativeWindowHandle
                    if hwnd:
                        set_foreground_window(hwnd)
                        time.sleep(0.2)
                except Exception:
                    pass
        except Exception:
            pass
        
    except Exception as e:
        print(f"[{datetime.now()}] Error switching desktop: {e}")


def detect_desktops_with_vscode() -> list:
    """
    Auto-detect which virtual desktops have VS Code windows open.
    Returns a list of desktop numbers (1-based) that have VS Code, or [0] for current only.
    """
    print(f"[{datetime.now()}] Scanning desktops for VS Code windows...")
    _log_verbose(f"  Note: This will cycle through up to {MAX_DESKTOPS_TO_SCAN} desktops...")
    desktops_with_vscode = []
    original_desktop = None
    
    try:
        # Check current desktop first to remember where we started
        current_vscode = find_all_vscode_windows(timeout=0.5)
        if current_vscode:
            _log_verbose(f"  ✓ Current desktop: Found {len(current_vscode)} VS Code window(s)")
        
        # First, go to desktop 1
        _log_verbose("  Navigating to desktop 1...")
        for _ in range(MAX_DESKTOPS_TO_SCAN):
            keyboard.send('win+ctrl+left')
            time.sleep(0.15)
        time.sleep(DESKTOP_SCAN_WAIT)
        
        # Scan each desktop
        for desktop_num in range(1, MAX_DESKTOPS_TO_SCAN + 1):
            # Check for VS Code windows on current desktop
            vscode_windows = find_all_vscode_windows(timeout=0.5)
            
            if vscode_windows:
                desktops_with_vscode.append(desktop_num)
                _log_verbose(f"  ✓ Desktop {desktop_num}: Found {len(vscode_windows)} VS Code window(s)")
                if original_desktop is None:
                    original_desktop = desktop_num  # Remember first desktop with VS Code
            else:
                _log_verbose(f"    Desktop {desktop_num}: No VS Code windows")
            
            # Move to next desktop (will wrap around if at the end)
            if desktop_num < MAX_DESKTOPS_TO_SCAN:
                keyboard.send('win+ctrl+right')
                time.sleep(DESKTOP_SCAN_WAIT)
            
            # If we find no new windows for 4 consecutive desktops, assume we've checked them all
            if len(desktops_with_vscode) > 0 and desktop_num > desktops_with_vscode[-1] + 4:
                _log_verbose(f"  No more VS Code windows found after desktop {desktops_with_vscode[-1]}, stopping scan.")
                break
        
        if not desktops_with_vscode:
            print("  ⚠ No VS Code windows found on any desktop during scan!")
            _log_normal("  This might be due to:")
            _log_normal("    - VS Code windows not being detectable during fast switching")
            _log_normal("    - VS Code on a desktop beyond the scan range")
            _log_normal("  Recommendation: Set DESKTOPS_TO_CHECK = [0] to work on current desktop only")
            return [0]
        
        print(f"[{datetime.now()}] Auto-detected desktops: {desktops_with_vscode}")
        
        # Return to the first desktop with VS Code
        if original_desktop:
            _log_verbose(f"  Returning to desktop {original_desktop}...")
            switch_to_desktop(original_desktop)
        
        return desktops_with_vscode
        
    except Exception as e:
        print(f"[{datetime.now()}] Error during desktop detection: {e}")
        print("  Falling back to current desktop only.")
        return [0]


# Windows API structures (defined once at module level for performance)
class _POINT(ctypes.Structure):
    """Windows POINT structure for cursor position."""
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# Windows API functions via ctypes (no extra dependencies needed)
def get_cursor_pos():
    """Get current mouse cursor position using ctypes."""
    pt = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def set_cursor_pos(x, y):
    """Set mouse cursor position instantly using ctypes."""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def get_foreground_window():
    """Get the currently active/focused window handle."""
    return ctypes.windll.user32.GetForegroundWindow()


def set_foreground_window(hwnd):
    """Set the active/focused window by handle."""
    try:
        ctypes.windll.user32.SetForegroundWindow(int(hwnd))
    except Exception:
        pass


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _get_tick_count_ms() -> int:
    """Return the system tick count in milliseconds (handles 32-bit fallback)."""
    try:
        return ctypes.windll.kernel32.GetTickCount64()
    except AttributeError:
        # Fall back to 32-bit counter on older systems
        return ctypes.windll.kernel32.GetTickCount()


def get_system_idle_seconds() -> float | None:
    """Return seconds since the last user input event (keyboard or mouse)."""
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None

        now_ms = _get_tick_count_ms()
        idle_ms = int(now_ms) - int(info.dwTime)
        if idle_ms < 0:
            idle_ms += 2 ** 32  # Handle 32-bit wraparound when using GetTickCount
        return idle_ms / 1000.0
    except Exception:
        return None


def detect_recent_user_input(now: datetime) -> tuple[bool, float | None]:
    """
    Return (is_active, idle_seconds) checking keyboard activity and significant mouse movement.
    
    Mouse jigglers typically move the cursor only a few pixels. We ignore mouse movement
    smaller than MOUSE_MOVEMENT_THRESHOLD pixels to avoid false positives from jigglers.
    
    We track keyboard activity via the keyboard hook (last_key_time) and only count
    mouse movement if it exceeds the threshold.
    """
    global last_key_time, last_mouse_pos, last_significant_input_time

    # Get current mouse position
    current_mouse_pos = get_cursor_pos()
    
    # Check if mouse moved significantly since last check
    if last_mouse_pos is not None:
        dx = abs(current_mouse_pos[0] - last_mouse_pos[0])
        dy = abs(current_mouse_pos[1] - last_mouse_pos[1])
        distance = (dx * dx + dy * dy) ** 0.5
        if distance >= MOUSE_MOVEMENT_THRESHOLD:
            last_significant_input_time = now
    
    # Update last mouse position
    last_mouse_pos = current_mouse_pos
    
    # Keyboard activity is tracked by the keyboard hook which updates last_key_time
    # Update significant input time if keyboard was used more recently
    if last_key_time != datetime.min and last_key_time > last_significant_input_time:
        last_significant_input_time = last_key_time
    
    # Calculate idle time since last significant input
    if last_significant_input_time == datetime.min:
        # No significant input detected yet - not active
        return False, None
    
    idle_seconds = (now - last_significant_input_time).total_seconds()
    is_active = idle_seconds < TYPING_IDLE_SECONDS
    
    return is_active, idle_seconds


def find_all_vscode_windows(timeout: float = 0.5) -> list:
    """
    Find ALL VS Code windows by title suffix.
    Returns a list of Controls (WindowControl or PaneControl).
    """
    vscode_windows = []
    # searchDepth=1 keeps it fast: top-level windows only.
    try:
        for w in auto.GetRootControl().GetChildren():
            # VS Code can be WindowControl or PaneControl depending on the state
            if isinstance(w, (auto.WindowControl, auto.PaneControl)):
                try:
                    name = w.Name
                    if name and name.endswith(VSCODE_TITLE_SUFFIX):
                        if w.Exists(timeout):
                            vscode_windows.append(w)
                except Exception:
                    continue
    except Exception as e:
        # Handle COM errors when UI elements become invalid during enumeration
        # This is a transient error that can occur when windows are closing/opening
        print(f"  ⚠️  Warning: UI enumeration error (likely transient): {e}")
        # Return whatever windows we found before the error
    return vscode_windows


def get_chat_confirmation_text(button: auto.Control) -> str:
    """
    Extract the chat confirmation text from the dialog containing the Allow button.
    Walks up the parent hierarchy to find the dialog group.
    """
    try:
        # Walk up to find the "Chat Confirmation Dialog" group
        parent = button.GetParentControl()
        depth = 0
        while parent and depth < 10:
            try:
                name = parent.Name
                if name and "Chat Confirmation Dialog" in name:
                    # Found the dialog, extract the text after "Chat Confirmation Dialog"
                    # Format: "Chat Confirmation Dialog Run `bash` command? "
                    return name.replace("Chat Confirmation Dialog", "").strip()
                
                # Also check for confirmation text pattern
                if name and "Chat confirmation required:" in name:
                    # This appears to be the full command text
                    # Format: "Chat confirmation required: Run `bash` command?: <command>"
                    parts = name.split(":", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()[:100]  # Limit to 100 chars
                    
            except Exception:
                pass
            
            parent = parent.GetParentControl()
            depth += 1
    except Exception:
        pass
    
    return "Unable to extract chat text"


def _invoke_control(control: auto.Control) -> bool:
    """Attempt to activate a control via Invoke pattern when clicking isn't possible."""
    try:
        getter = getattr(control, "GetInvokePattern", None)
        if callable(getter):
            invoke_pattern = getter()
            if invoke_pattern:
                invoke_pattern.Invoke()  # type: ignore[attr-defined]
                return True
    except Exception:
        pass
    return False


def _scroll_control_into_view(control: auto.Control) -> bool:
    """Try to scroll a virtualized control into view via the ScrollItem pattern."""
    try:
        getter = getattr(control, "GetScrollItemPattern", None)
        if callable(getter):
            pattern = getter()
            if pattern:
                pattern.ScrollIntoView()  # type: ignore[attr-defined]
                time.sleep(0.05)
                return True
    except Exception:
        pass
    return False


def click_button_instantly(btn: auto.Control):
    """
    Click a button by instantly teleporting the mouse to it and back.
    Also saves and restores the active window focus so typing continues in the original window.
    Uses direct Win32 API calls for instant movement without animation.
    """
    # Save current mouse position AND active window
    original_pos = get_cursor_pos()
    original_window = get_foreground_window()
    
    try:
        # Get button's bounding rectangle
        rect = btn.BoundingRectangle
        
        # Check if button has valid coordinates; attempt to bring it into view if not
        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            _scroll_control_into_view(btn)
            time.sleep(0.1)
            rect = btn.BoundingRectangle

        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            if _invoke_control(btn):
                return
            print(
                f"[{datetime.now()}] Warning: button has no visible bounds; skipping direct click."
            )
            return
        
        # Find the parent VS Code window and bring it to foreground
        try:
            parent = btn.GetParentControl()
            depth = 0
            vs_code_window = None
            while parent and depth < 15:
                if isinstance(parent, (auto.WindowControl, auto.PaneControl)):
                    name = parent.Name or ""
                    if name.endswith(VSCODE_TITLE_SUFFIX):
                        vs_code_window = parent
                        break
                parent = parent.GetParentControl()
                depth += 1
            
            # Activate VS Code window if found
            if vs_code_window:
                try:
                    vs_code_window.SetActive()
                    time.sleep(0.05)
                except Exception:
                    pass
        except Exception:
            pass
        
        # Calculate center of button
        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2
        
        # Instantly move mouse to button center
        set_cursor_pos(center_x, center_y)
        time.sleep(0.02)  # Slightly longer delay to ensure position is set
        
        # Try multiple click methods for better reliability
        click_succeeded = False
        try:
            # Method 1: Standard Click
            btn.Click(simulateMove=False)
            click_succeeded = True
        except Exception:
            pass
        
        if not click_succeeded:
            # Method 2: Try Invoke pattern
            if _invoke_control(btn):
                click_succeeded = True
        
        if not click_succeeded:
            # Method 3: Send Enter key to the button
            try:
                btn.SetFocus()
                time.sleep(0.02)
                auto.SendKeys('{Enter}')
                click_succeeded = True
            except Exception:
                pass
        
        if not click_succeeded:
            # Method 4: Physical mouse click via Win32
            try:
                import ctypes
                # Left mouse button down
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.01)
                # Left mouse button up
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            except Exception:
                pass
        
    finally:
        # Restore mouse to original position
        time.sleep(0.05)  # Longer wait to ensure click is processed
        set_cursor_pos(original_pos[0], original_pos[1])
        
        # Restore the original active window so user can keep typing
        if original_window:
            time.sleep(0.05)  # Longer delay to ensure click is processed
            set_foreground_window(original_window)


def _control_no_longer_visible(ctrl: auto.Control) -> bool:
    """Return True when a control no longer exists or raises during lookup."""
    try:
        # Check if control exists with longer timeout
        if not ctrl.Exists(0.2):
            return True
        
        # Additional check: verify the button still has valid bounds
        rect = ctrl.BoundingRectangle
        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            return True
            
        # Check if button is still enabled and visible
        try:
            if not ctrl.IsEnabled:
                return True
            # For buttons that fade out, check if they have zero size
            # Don't check for negative coords - they're valid for multi-monitor setups
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return True
        except Exception:
            pass
            
        return False
    except Exception:
        # Any exception means the control is gone
        return True


def click_button_with_verification(
    btn: auto.Control,
    description: str,
    *,
    max_attempts: int = 3,
    post_click_wait: float = 0.3,
) -> bool:
    """
    Click a button and verify it disappeared before proceeding.

    Retries up to ``max_attempts`` times when the control still exists, helping
    with dialogs that occasionally require multiple clicks to register.

    Returns True if the button appears to have been handled, False otherwise.
    """

    for attempt in range(1, max_attempts + 1):
        try:
            click_button_instantly(btn)
        except Exception as exc:
            if attempt >= max_attempts:
                print(
                    f"  ✗ Failed to click {description} after {attempt} attempt(s): {exc}"
                )
                return False
            print(
                f"  ⚠ Error clicking {description} (attempt {attempt}): {exc}. Retrying..."
            )
            time.sleep(0.15)
            continue

        # Wait progressively longer after each attempt
        wait_time = post_click_wait * (1 + (attempt - 1) * 0.5)
        time.sleep(wait_time)
        
        # Check multiple times with small delays to handle slow UI updates
        button_gone = False
        for check in range(3):
            if _control_no_longer_visible(btn):
                button_gone = True
                break
            time.sleep(0.1)
        
        if button_gone:
            if attempt > 1:
                print(f"  ✓ {description} registered after {attempt} attempts.")
            return True

        if attempt < max_attempts:
            print(
                f"  ⚠ {description} still detected after attempt {attempt}; trying again..."
            )
            _scroll_control_into_view(btn)
            time.sleep(0.08)
        else:
            print(
                f"  ⚠ {description} still present after {max_attempts} attempts; moving on."
            )
            # Try one last time with keyboard shortcut as fallback
            try:
                print("  → Trying keyboard shortcut Ctrl+Enter as fallback...")
                auto.SendKeys('^{Enter}')
                time.sleep(0.3)
                if _control_no_longer_visible(btn):
                    print(f"  ✓ {description} dismissed via keyboard shortcut.")
                    return True
            except Exception as e:
                print(f"  ✗ Keyboard fallback also failed: {e}")

    return False


def scroll_chat_to_bottom(vs_win: auto.Control):
    """
    Try to scroll the chat panel to the bottom to reveal any hidden Allow buttons.
    Uses keyboard shortcuts which are more reliable than UI Automation scroll methods.
    Preserves both mouse position and active window focus.
    """
    def _find_chat_controls(max_depth=45) -> List[auto.Control]:
        matches: List[auto.Control] = []
        target_keywords = {"chat", "inline chat", "chat list", "chat messages"}

        def search(control, depth=0):
            if depth > max_depth or len(matches) >= 6:
                return
            try:
                name = (control.Name or "").strip().lower()
                if name:
                    if any(keyword in name for keyword in target_keywords):
                        if isinstance(
                            control,
                            (
                                auto.ListControl,
                                auto.PaneControl,
                                auto.DocumentControl,
                                auto.GroupControl,
                            ),
                        ):
                            matches.append(control)

                for child in control.GetChildren():
                    search(child, depth + 1)
            except KeyboardInterrupt:
                raise
            except Exception:
                return

        search(vs_win)
        return matches

    def _focus_control(ctrl: auto.Control) -> bool:
        try:
            if not ctrl.Exists(0.2):
                return False
            try:
                ctrl.SetFocus()
                return True
            except Exception:
                rect = ctrl.BoundingRectangle
                if rect.left == rect.right and rect.top == rect.bottom:
                    return False
                center_x = (rect.left + rect.right) // 2
                center_y = (rect.top + rect.bottom) // 2
                set_cursor_pos(center_x, center_y)
                time.sleep(0.02)
                ctrl.Click(simulateMove=False)
                return True
        except Exception:
            return False

    original_pos = get_cursor_pos()
    original_window = get_foreground_window()

    try:
        candidates = _find_chat_controls()
        if not candidates:
            candidates = [vs_win]

        for ctrl in candidates:
            if not _focus_control(ctrl):
                continue

            time.sleep(0.05)
            for _ in range(3):
                auto.SendKeys('{Ctrl}{End}')
                time.sleep(0.08)
            auto.SendKeys('{Ctrl}{Down}')
            time.sleep(0.05)
            return True
    except Exception:
        return False
    finally:
        set_cursor_pos(original_pos[0], original_pos[1])
        if original_window:
            time.sleep(0.02)
            set_foreground_window(original_window)

    return False


def find_try_again_buttons(vs_win: auto.Control, max_depth=50) -> list:
    """
    Recursively search for "Try Again" buttons (rate limit recovery).
    Returns list of button controls.
    """
    found_buttons = []
    
    def search_recursive(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name
                if name and "Try Again" in name:
                    if control.Exists(0.1):
                        found_buttons.append(control)
            
            # Recurse into children
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
                
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found_buttons


def find_focus_terminal_buttons(vs_win: auto.Control, max_depth=50) -> list:
    """
    Recursively search for "Focus Terminal" buttons that require user attention.
    Returns list of button controls.
    """
    found_buttons = []
    
    def search_recursive(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            if isinstance(control, auto.ButtonControl):
                name = control.Name
                if name and "Focus Terminal" in name:
                    if control.Exists(0.1):
                        found_buttons.append(control)
            
            # Recurse into children
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
                
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found_buttons


def find_rate_limit_text_panels(
    vs_win: auto.Control,
    max_depth=60,
    *,
    window_title: str | None = None,
    now: datetime | None = None,
) -> List[auto.Control]:
    """Search for visible controls whose Name matches known rate-limit messages."""
    matches: List[auto.Control] = []
    now = now or datetime.now()
    _prune_rate_limit_panel_cache(now)
    window_label = (window_title or getattr(vs_win, "Name", None) or "Unknown").strip()

    def search_recursive(control, depth=0):
        if depth > max_depth:
            return

        try:
            name = control.Name
            if name:
                normalized = name.replace("\r\n", "\n").lower()
                recent_text, window_start = _recent_text_window(normalized)
                match_relative = _earliest_rate_limit_match(recent_text)
                match_index = None if match_relative is None else window_start + match_relative
                if match_index is not None and not _is_stale_rate_limit_text(normalized, match_index):
                    if control.Exists(0.1):
                        panel_key = _rate_limit_panel_identifier(control, window_label, normalized)
                        if _mark_rate_limit_panel_seen(panel_key, now):
                            matches.append(control)

            for child in control.GetChildren():
                search_recursive(child, depth + 1)

        except Exception:
            pass

    search_recursive(vs_win)
    return matches


def detect_rate_limit_in_window(vs_win: auto.Control) -> Dict[str, int]:
    """Return counts of Try Again buttons and rate-limit panels."""
    try_again = len(find_try_again_buttons(vs_win))
    panels = len(find_rate_limit_text_panels(vs_win))
    return {"try_again": try_again, "panels": panels}


def get_chat_panel_text_snapshot(vs_win: auto.Control, max_depth: int = 60) -> str:
    """
    Get a snapshot of all text content in the chat panel area.
    Used to detect if new output is being generated (agent is working).
    """
    text_parts: List[str] = []
    
    def collect_text(control, depth=0):
        if depth > max_depth:
            return
        try:
            name = control.Name
            if name and len(name) > 10:  # Skip short labels
                text_parts.append(name)
            for child in control.GetChildren():
                collect_text(child, depth + 1)
        except Exception:
            pass
    
    collect_text(vs_win)
    return "|||".join(text_parts)  # Use delimiter to detect new segments


def verify_rate_limit_with_activity_check(
    vs_win: auto.Control,
    allow_buttons: List[auto.Control],
    window_title: str,
    try_again_buttons: List[auto.Control] | None = None,
) -> Tuple[bool | None, int]:
    """
    Verify if a suspected rate limit is real by clicking Allow or Try Again buttons 
    and monitoring for activity.
    
    Strategy:
    1. Take a snapshot of the current chat panel text AND rate limit indicators
    2. Click an Allow button (or Try Again if no Allow available)
    3. Wait and monitor for new output (text changes)
    4. If new text appears that's NOT a rate limit message → agent is working, not rate limited
    5. If a NEW rate limit message/button appears → confirmed rate limit
    6. If the same old rate limit indicators remain → likely stale, not a real rate limit
    
    Args:
        vs_win: The VS Code window control
        allow_buttons: List of Allow button controls to try clicking
        window_title: Window title for logging
        try_again_buttons: Optional list of Try Again buttons to use for verification
    
    Returns:
        Tuple of (is_rate_limited: bool | None, buttons_clicked: int)
        - True: Confirmed rate limited
        - False: Confirmed NOT rate limited (agents working)
        - None: Could not verify (no buttons available)
    """
    # Combine Allow and Try Again buttons - both can be used for verification
    # Try Again buttons work the same way: they either continue or show rate limit again
    all_verify_buttons: List[Tuple[str, auto.Control]] = []
    
    for btn in (allow_buttons or []):
        all_verify_buttons.append(("Allow", btn))
    
    for btn in (try_again_buttons or []):
        all_verify_buttons.append(("Try Again", btn))
    
    if not all_verify_buttons:
        # No buttons at all = can't verify
        print(f"  [VERIFY] No Allow or Try Again buttons available for verification in '{window_title[:50]}...'")
        return None, 0  # None means "couldn't verify" - caller should try elsewhere
    
    buttons_to_try = min(len(all_verify_buttons), RATE_LIMIT_VERIFY_CLICKS)
    buttons_clicked = 0
    
    button_types = set(t for t, _ in all_verify_buttons[:buttons_to_try])
    type_label = "/".join(sorted(button_types))
    print(f"  [VERIFY] Testing rate limit with {buttons_to_try} {type_label} click(s) in '{window_title[:50]}...'")
    
    for btn_idx, (btn_type, btn) in enumerate(all_verify_buttons[:buttons_to_try], 1):
        if is_paused:
            print("  [VERIFY] Paused during verification")
            return True, buttons_clicked
        
        try:
            # Check button still exists
            if not btn.Exists(0.3):
                print(f"  [VERIFY] {btn_type} button {btn_idx} no longer exists, skipping...")
                continue
            
            # Check for valid bounds (skip invisible buttons)
            if not _has_valid_bounds(btn):
                # Try scrolling button into view
                if _try_scroll_and_check_bounds(btn, vs_win):
                    _log_verbose(f"  [VERIFY] Scrolled {btn_type} button {btn_idx} into view")
                else:
                    print(f"  [VERIFY] {btn_type} button {btn_idx} has zero bounds (invisible), skipping...")
                    continue
            
            # Take snapshot BEFORE clicking - both text AND rate limit indicator counts
            snapshot_before = get_chat_panel_text_snapshot(vs_win)
            detection_before = detect_rate_limit_in_window(vs_win)
            try_again_count_before = detection_before.get('try_again', 0)
            
            # Scroll button into view
            _scroll_control_into_view(btn)
            time.sleep(0.05)  # Brief wait after scroll
            
            # Get chat text for logging (only for Allow buttons)
            if btn_type == "Allow":
                chat_text = get_chat_confirmation_text(btn)
                print(f"  [VERIFY] Clicking {btn_type} button {btn_idx}: {chat_text[:60]}...")
            else:
                print(f"  [VERIFY] Clicking {btn_type} button {btn_idx}...")
            
            # Click the button
            try:
                click_button_instantly(btn)
                buttons_clicked += 1
                if btn_type == "Allow":
                    record_allow_click(window_title)
                # Note: Try Again clicks that succeed also consume quota, but we'll count them
                # in click_try_again_buttons_on_desktops instead
            except Exception as e:
                print(f"  [VERIFY] Error clicking {btn_type} button {btn_idx}: {e}")
                continue
            
            # Monitor for activity over the verification window
            activity_detected = False
            new_rate_limit_detected = False
            check_count = int(RATE_LIMIT_VERIFY_WAIT_SECONDS / RATE_LIMIT_ACTIVITY_CHECK_INTERVAL)
            
            for check_idx in range(check_count):
                time.sleep(RATE_LIMIT_ACTIVITY_CHECK_INTERVAL)
                
                # Check for NEW rate limit indicators (compare to before)
                detection_after = detect_rate_limit_in_window(vs_win)
                try_again_count_after = detection_after.get('try_again', 0)
                
                # A NEW Try Again button appearing means rate limit is real
                # (clicking Try Again should dismiss it if not rate limited)
                if try_again_count_after > try_again_count_before:
                    print(f"  [VERIFY] ⚠ NEW rate limit indicator appeared after click {btn_idx} (Try Again: {try_again_count_before} → {try_again_count_after})")
                    new_rate_limit_detected = True
                    break
                
                # Check for new output (text changes that aren't rate limit messages)
                snapshot_after = get_chat_panel_text_snapshot(vs_win)
                if snapshot_after != snapshot_before:
                    # Text changed - check if it's meaningful output (not just UI changes)
                    new_text_length = len(snapshot_after) - len(snapshot_before)
                    if new_text_length > 50:  # Significant new content
                        print(f"  [VERIFY] ✓ Activity detected! New output appearing (+{new_text_length} chars)")
                        activity_detected = True
                        break
                    elif new_text_length < -50:  # Significant text REMOVED (Try Again dismissed)
                        # If Try Again button count also decreased, agent is working
                        if try_again_count_after < try_again_count_before:
                            print("  [VERIFY] ✓ Try Again button dismissed and text changed - agent working!")
                            activity_detected = True
                            break
            
            if activity_detected:
                # Agent is working - this is NOT a real rate limit
                print("  [VERIFY] ✓ Agent is actively producing output - NOT rate limited")
                return False, buttons_clicked
            
            if new_rate_limit_detected:
                # Confirmed rate limit - NEW rate limit indicator appeared
                print(f"  [VERIFY] ✗ Confirmed rate limit after {btn_idx} click(s)")
                return True, buttons_clicked
            
            # Neither activity nor new rate limit - check if button was dismissed
            detection_final = detect_rate_limit_in_window(vs_win)
            if detection_final.get('try_again', 0) < try_again_count_before:
                # Try Again button was dismissed without new one appearing - agent might be working
                print("  [VERIFY] ✓ Try Again button dismissed, no new rate limit - assuming agent working")
                return False, buttons_clicked
            
            print(f"  [VERIFY] No activity or change after click {btn_idx}, trying next button...")
            
        except Exception as e:
            print(f"  [VERIFY] Error during verification click {btn_idx}: {e}")
    
    # If we got here, we clicked buttons but saw neither clear activity nor new rate limit
    # If we had Try Again buttons before and still have the SAME number, they're likely stale
    if buttons_clicked > 0:
        # We clicked something but nothing changed - likely stale rate limit indicators
        print(f"  [VERIFY] ✓ Clicked {buttons_clicked} button(s) with no new rate limit - assuming stale indicators")
        return False, buttons_clicked
    
    # No rate limit detected, but also no clear activity - assume OK
    print(f"  [VERIFY] ✓ No new rate limit after {buttons_clicked} verification click(s)")
    return False, buttons_clicked


# ============================================================================
# QUICK PANEL STATE DETECTION
# ============================================================================

class QuickPanelState:
    """Quick panel state detection result."""
    RUNNING = "RUNNING"      # Cancel button visible - agent is actively working
    WAITING = "WAITING"      # Send button visible + Allow button found - needs user action
    FINISHED = "FINISHED"    # Send button visible + no Allow button - agent completed
    UNKNOWN = "UNKNOWN"      # Could not determine state (no chat panel?)


def detect_panel_state_quick(vs_win: auto.Control, max_depth: int = 50) -> Tuple[str, bool, bool]:
    """
    Quickly detect panel state by looking for Cancel/Send button and Allow button.
    
    This is a fast check that determines:
    - RUNNING: Cancel (Alt+Backspace) button visible → agent is actively working
    - WAITING: Send button visible + Allow button found → needs user action
    - FINISHED: Send button visible + no Allow button → agent completed work
    
    Args:
        vs_win: VS Code window control
        max_depth: Maximum recursion depth for UI tree search
        
    Returns:
        Tuple of (state, has_cancel, has_allow) where:
        - state: QuickPanelState value (RUNNING, WAITING, FINISHED, UNKNOWN)
        - has_cancel: True if Cancel button found (agent running)
        - has_allow: True if Allow button found (needs user action)
    """
    has_cancel = False
    has_send = False
    has_allow = False
    
    # Button patterns:
    # - Cancel (Alt+Backspace) → RUNNING (agent working)
    # - Send [Alt] Send to New Chat... → IDLE (ready for input)
    # - Allow (Ctrl+Enter) → needs user action
    ALLOW_PATTERNS = ["Allow (Ctrl+Enter)", "Allow"]
    
    def search_buttons(control, depth=0):
        nonlocal has_cancel, has_send, has_allow
        
        if depth > max_depth:
            return
        
        # Early exit if we found Cancel (definitely running)
        if has_cancel:
            return
            
        try:
            # Check Button and SplitButton controls
            if control.ControlType in [auto.ControlType.ButtonControl, auto.ControlType.SplitButtonControl]:
                name = control.Name or ""
                
                # Check for Cancel button (RUNNING indicator)
                if "Cancel" in name and ("Alt+Backspace" in name or "Backspace" in name):
                    has_cancel = True
                    return  # Found Cancel - definitely running, stop searching
                
                # Check for Send button (IDLE indicator)
                if "Send" in name and "Cancel" not in name:
                    has_send = True
                
                # Check for Allow button (needs action)
                if name in ALLOW_PATTERNS or (name and name.startswith("Allow")):
                    has_allow = True
            
            # Recurse into children
            for child in control.GetChildren():
                search_buttons(child, depth + 1)
                if has_cancel:
                    return
                    
        except Exception:
            pass
    
    search_buttons(vs_win)
    
    # Determine state
    if has_cancel:
        return QuickPanelState.RUNNING, True, has_allow
    elif has_send:
        if has_allow:
            return QuickPanelState.WAITING, False, True
        else:
            return QuickPanelState.FINISHED, False, False
    else:
        return QuickPanelState.UNKNOWN, False, has_allow


def get_panel_states_summary(vscode_windows: List[auto.Control]) -> Dict[str, int]:
    """
    Get a summary of panel states across multiple VS Code windows.
    
    Args:
        vscode_windows: List of VS Code window controls
        
    Returns:
        Dict with counts: {'RUNNING': n, 'WAITING': n, 'FINISHED': n, 'UNKNOWN': n}
    """
    summary = {
        QuickPanelState.RUNNING: 0,
        QuickPanelState.WAITING: 0,
        QuickPanelState.FINISHED: 0,
        QuickPanelState.UNKNOWN: 0,
    }
    
    for vs_win in vscode_windows:
        state, _, _ = detect_panel_state_quick(vs_win)
        summary[state] += 1
    
    return summary


def find_all_allow_buttons_in_window(vs_win: auto.Control, max_depth: int = 70) -> List[auto.Control]:
    """Find all Allow buttons in a VS Code window."""
    found_buttons: List[auto.Control] = []
    
    # Allow button names (full and short versions)
    ALLOW_NAMES = ["Allow (Ctrl+Enter)", "Allow"]
    
    def search_recursive(control, depth=0):
        if depth > max_depth:
            return
        try:
            # Check both Button and SplitButton control types
            if control.ControlType in [auto.ControlType.ButtonControl, auto.ControlType.SplitButtonControl]:
                name = control.Name
                if name in ALLOW_NAMES:
                    if control.Exists(0.1):
                        found_buttons.append(control)
            for child in control.GetChildren():
                search_recursive(child, depth + 1)
        except Exception:
            pass
    
    search_recursive(vs_win)
    return found_buttons


def click_try_again_buttons_on_desktops(desktops_to_process: List[int]) -> Tuple[int, int]:
    """
    Re-scan all configured desktops and click every Try Again button once.
    
    Returns:
        Tuple of (total_clicked, successful_continues) where successful_continues
        is the count of Try Again clicks that resulted in agent activity (not immediate rate limit).
        These count against the rate limit quota.
    """
    total_clicked = 0
    successful_continues = 0

    for desktop_num in desktops_to_process:
        if is_paused:
            print(f"\n[{datetime.now()}] Manual pause detected while clearing 'Try Again' buttons. Aborting sweep...")
            return total_clicked, successful_continues

        # Only switch if we're working across multiple desktops
        if _needs_desktop_switch(desktop_num):
            switch_to_desktop(desktop_num)
            time.sleep(0.5)  # Reduced wait - pyvda is faster

        vscode_windows = find_all_vscode_windows()
        if not vscode_windows:
            continue

        for vs_win in vscode_windows:
            if is_paused:
                print(f"\n[{datetime.now()}] Manual pause detected while clearing 'Try Again' buttons. Aborting sweep...")
                return total_clicked, successful_continues

            try_again_btns = find_try_again_buttons(vs_win)
            if not try_again_btns:
                continue

            window_title = vs_win.Name[:60] if vs_win.Name else "Unknown"
            full_window_title = vs_win.Name if vs_win.Name else "Unknown"
            print(
                f"  Found {len(try_again_btns)} 'Try Again' button(s) after cooldown in '{window_title}...'"
            )

            for btn in try_again_btns:
                try:
                    if btn.Exists(0.5):
                        # Skip buttons with zero bounds (invisible)
                        now = datetime.now()
                        if not _has_valid_bounds(btn):
                            # Try scrolling the button into view first
                            if _try_scroll_and_check_bounds(btn, vs_win):
                                print("  ✓ Scrolled 'Try Again' button into view")
                            else:
                                # Still no valid bounds after scrolling
                                if _should_skip_zero_bounds_button(full_window_title, "Try Again", btn, now):
                                    continue  # Silently skip
                                _mark_zero_bounds_button(full_window_title, "Try Again", btn, now)
                                continue
                        
                        description = "Try Again button"
                        if click_button_with_verification(
                            btn,
                            description,
                            max_attempts=3,
                            post_click_wait=0.3,
                        ):
                            total_clicked += 1
                            
                            # Wait and check if agent continues or immediately rate limits again
                            time.sleep(0.5)  # Brief wait for agent response
                            detection = detect_rate_limit_in_window(vs_win)
                            
                            if detection['try_again'] == 0 and detection['panels'] == 0:
                                # No immediate rate limit - agent is continuing!
                                # This counts as consuming rate limit quota
                                successful_continues += 1
                                record_allow_click(full_window_title)
                                print(f"    ✓ {description} #{total_clicked} - agent continuing (counted as Allow)")
                            else:
                                # Immediately rate limited again - don't count
                                print(f"    ⚠ {description} #{total_clicked} - immediately rate limited again (not counted)")
                        else:
                            print("    ⚠ Unable to confirm Try Again click; leaving it for next pass")
                        time.sleep(0.15)
                except Exception as e:
                    print(f"    ✗ Error clicking Try Again: {e}")

    return total_clicked, successful_continues


def click_all_action_buttons(vs_win: auto.Control, timeout: float = 0.5) -> Tuple[dict, Dict[str, int]]:
    """
    Look for ALL Copilot action buttons inside the VS Code window and click them.
    Searches for:
    - 'Allow (Ctrl+Enter)' buttons (for command confirmations)
    - 'Keep All Edits (Ctrl+Enter)' buttons (for accepting all edits)
    - 'Keep this Change (Ctrl+Y)' buttons (for accepting individual edits)
    - 'Keep Chat Edits in this File (Ctrl+Shift+Y)' buttons
    
    Returns a tuple of (clicked_counts, rate_limit_counts) where:
    - clicked_counts tallies Allow vs Keep Edits clicks
    - rate_limit_counts holds counts of Try Again buttons and rate limit panels
    """
    clicked_counts = {
        'allow': 0,
        'keep_edits': 0
    }
    rate_limit_counts = {'try_again': 0, 'panels': 0}
    
    # All button names we want to click (including Try Again for rate limit recovery)
    # Support both full names and shorter variants (VS Code may use different labels)
    KEEP_BUTTON_NAMES = [
        "Keep All Edits (Ctrl+Enter)",
        "Keep this Change (Ctrl+Y)",
        "Keep Chat Edits in this File (Ctrl+Shift+Y)",
        "Keep",  # Short version with dropdown
    ]
    ALLOW_BUTTON_NAMES = [
        "Allow (Ctrl+Enter)",
        "Allow",  # Short version with dropdown
    ]
    TRY_AGAIN_BUTTON_NAME = "Try Again"
    ALL_ACTION_BUTTONS = ALLOW_BUTTON_NAMES + KEEP_BUTTON_NAMES + [TRY_AGAIN_BUTTON_NAME]
    
    # Control types to check (Button and SplitButton)
    CLICKABLE_CONTROL_TYPES = [
        auto.ControlType.ButtonControl,  # 50000
        auto.ControlType.SplitButtonControl,  # 50031
    ]
    
    # CRITICAL: Activate the window AGGRESSIVELY to ensure UI is rendered
    # Windows doesn't render controls for inactive windows on other desktops
    window_activated = False
    try:
        hwnd = vs_win.NativeWindowHandle
        if hwnd:
            # First attempt - use SetForegroundWindow
            set_foreground_window(hwnd)
            time.sleep(0.15)
            
            # Second attempt - use SetActive
            try:
                vs_win.SetActive()
                time.sleep(0.1)
            except Exception:
                pass
            
            # Third attempt - SetForegroundWindow again (sometimes needed twice)
            set_foreground_window(hwnd)
            time.sleep(0.15)
            
            window_activated = True
    except Exception:
        pass
    
    if not window_activated:
        try:
            vs_win.SetActive()
            time.sleep(0.1)
        except Exception:
            pass
    
    # Quick scroll to reveal hidden buttons - scroll both to bottom and slightly back
    # This helps ensure virtualized buttons are rendered before we search for them
    scroll_chat_to_bottom(vs_win)
    time.sleep(0.15)  # Extra wait for virtualized controls to render
    
    # Recursive function to find all action buttons (Allow, Keep Edits, Try Again)
    def find_all_action_buttons(control, depth=0, max_depth=50):
        if depth > max_depth:
            return []
        
        found = []
        try:
            # Check both Button and SplitButton control types
            if control.ControlType in CLICKABLE_CONTROL_TYPES:
                name = control.Name
                # Match exact names or "Try Again" prefix
                if name in ALL_ACTION_BUTTONS or (name and name.startswith("Try Again")):
                    found.append((name, control))
                # Debug: Log potential matches that are close but don't exactly match
                elif name and LOG_VERBOSITY == "verbose":
                    name_lower = name.lower()
                    if any(kw in name_lower for kw in ['allow', 'keep', 'skip']):
                        _log_verbose(f"  [DEBUG] Near-miss button: '{name}'")
            
            for child in control.GetChildren():
                found.extend(find_all_action_buttons(child, depth + 1, max_depth))
        except Exception:
            pass
        
        return found
    
    if is_paused:
        return clicked_counts, rate_limit_counts

    all_buttons = find_all_action_buttons(vs_win)
    
    # Debug log if no buttons found
    if not all_buttons and LOG_VERBOSITY == "verbose":
        window_title = (vs_win.Name or "Unknown")[:50]
        _log_verbose(f"  [DEBUG] No action buttons in: {window_title}")
    
    for button_name, btn in all_buttons:
        if is_paused:
            print(f"\n[{datetime.now()}] Manual pause detected while processing Copilot buttons. Stopping clicks in this window...")
            break
        try:
            window_title = vs_win.Name[:60] if vs_win.Name else "Unknown"
            now = datetime.now()

            # Scroll button into view
            _scroll_control_into_view(btn)
            
            # Re-check if button still exists
            try:
                if not btn.Exists(0.1):
                    continue
            except Exception:
                continue
            
            # Check if button has valid bounds (not invisible/zero bounds)
            # This prevents getting stuck in a loop clicking invisible buttons
            if not _has_valid_bounds(btn):
                # Try scrolling the button into view first
                if _try_scroll_and_check_bounds(btn, vs_win):
                    # Success! Log this to track scroll-fix effectiveness
                    short_title = window_title[:40] if len(window_title) > 40 else window_title
                    print(f"  ✓ Scrolled '{button_name}' into view in '{short_title}'")
                else:
                    # Still no valid bounds after scrolling - skip this button
                    # Check if we already know about this zero-bounds button
                    if _should_skip_zero_bounds_button(window_title, button_name, btn, now):
                        continue  # Silently skip, we already logged this button
                    # Mark this button and log once
                    _mark_zero_bounds_button(window_title, button_name, btn, now)
                    continue
            
            # Handle Allow buttons (both full name and short name with dropdown)
            if button_name in ALLOW_BUTTON_NAMES:
                chat_text = get_chat_confirmation_text(btn)
                print(f"\n[{datetime.now()}] Found Allow button in '{window_title}...'")
                print(f"  Chat text: {chat_text}")
                print("  Clicking...")
                if click_button_with_verification(btn, "Allow button", max_attempts=3):
                    clicked_counts['allow'] += 1
                    record_allow_click(window_title)
                    print("  ✓ Allow click counted")
                else:
                    print("  ✗ Allow click NOT counted (verification failed)")
                
            elif button_name in KEEP_BUTTON_NAMES:
                print(f"\n[{datetime.now()}] Found '{button_name}' in '{window_title}...'")
                print("  Clicking to accept edits...")
                if click_button_with_verification(btn, button_name, max_attempts=3):
                    clicked_counts['keep_edits'] += 1
                    print("  ✓ Keep Edits click counted")
                else:
                    print("  ✗ Keep Edits click NOT counted (verification failed)")
            
            elif button_name and button_name.startswith("Try Again"):
                print(f"\n[{datetime.now()}] Found Try Again button in '{window_title}...'")
                print("  Clicking to retry after rate limit...")
                if click_button_with_verification(btn, "Try Again button", max_attempts=3):
                    clicked_counts['allow'] += 1  # Count as allow since it continues the agent
                    record_allow_click(window_title)
                    print("  ✓ Try Again click counted")
                else:
                    print("  ✗ Try Again click NOT counted (verification failed)")
            
        except Exception as e:
            print(f"[{datetime.now()}] Error clicking {button_name}: {e}")

    return clicked_counts, rate_limit_counts


def main():
    global is_auto_paused, session_total_allow_clicks, session_total_keep_edits_clicks
    global zero_bounds_button_cache
    next_allowed_check = datetime.min
    
    # Clear zero-bounds cache at startup for fresh start
    zero_bounds_button_cache.clear()
    
    # Load persisted allow events from previous session
    _load_allow_events()
    
    # Register hotkeys using keyboard library as backup
    print("Hotkey configuration:")
    print(f"  {PAUSE_HOTKEY} - Toggle pause/resume")
    print(f"  {EXTRA_WAIT_HOTKEY} - Wait extra {EXTRA_PAUSE_SECONDS} seconds")
    print("  (Using polled detection for reliability)")
    
    try:
        # Try to also register with keyboard library as redundant backup
        keyboard.add_hotkey(PAUSE_HOTKEY, toggle_pause, suppress=False)
        keyboard.add_hotkey(EXTRA_WAIT_HOTKEY, trigger_extra_wait, suppress=False)
        print("  + Keyboard library hooks active (backup)")
    except Exception as e:
        print(f"  Note: Keyboard library unavailable ({e})")
    
    # Register keyboard event listener for auto-pause on typing
    if AUTO_PAUSE_ON_TYPING:
        try:
            keyboard.hook(on_key_event)
            print("\nAuto-pause on typing: ENABLED")
            print(f"  Will pause while typing, resume after {TYPING_IDLE_SECONDS}s idle")
            print("  (Also uses GetLastInputInfo for reliability)")
        except Exception as e:
            print("\nAuto-pause on typing: Using system idle detection only")
            print(f"  (Keyboard hook unavailable: {e})")

    print("\nStarting Copilot Allow auto-clicker...")
    print("Looking for buttons with names:")
    print("  - Allow: 'Allow (Ctrl+Enter)', 'Allow'")
    print("  - Keep:  'Keep All Edits (Ctrl+Enter)', 'Keep this Change (Ctrl+Y)', 'Keep', ...")
    print("  - Retry: 'Try Again', 'Try Again...'")
    print("  - (Also checking SplitButton controls)")
    print("\nPanel Tracking: ENABLED")
    print(f"  - Panel idle threshold:     {PANEL_IDLE_THRESHOLD_MINUTES} minutes (from panel_tracker)")
    print(f"  - Panel finished threshold: {PANEL_FINISHED_THRESHOLD_MINUTES} minutes (from panel_tracker)")
    print("  - Will monitor finished panels and send follow-up prompts")
    print("\nNo-Windows Loop Detection: ENABLED")
    print(f"  - Speech warning after {NO_WINDOWS_LOOP_WARN_THRESHOLD} consecutive 'no windows' cycles")
    print(f"  - Force desktop resync after {NO_WINDOWS_LOOP_FORCE_RESYNC_AFTER} cycles")
    print("Press Ctrl+C to stop.\n")
    
    # Determine which desktops to check
    if DESKTOPS_TO_CHECK == "auto":
        print("Desktop mode: Auto-detecting desktops with VS Code...")
        desktops_list = detect_desktops_with_vscode()
    elif DESKTOPS_TO_CHECK == [0]:
        print("Desktop mode: Current desktop only\n")
        desktops_list = [0]
    else:
        print(f"Desktop mode: Manually configured desktops {DESKTOPS_TO_CHECK}\n")
        desktops_list = DESKTOPS_TO_CHECK
    
    # Show final desktop configuration
    if desktops_list == [0]:
        print("Working on: Current desktop only\n")
    else:
        print(f"Working on: Desktops {desktops_list}")
        if USE_CACHED_HANDLES:
            print("  ⚡ CACHED HANDLES MODE: Scan desktops once, then use handles directly")
            print(f"     (Cache refresh every {CACHE_REFRESH_INTERVAL_MINUTES} minutes)")
        else:
            print("  📺 LEGACY MODE: Switch between desktops each cycle")
        print()

    def handle_rate_limit_detection(
        trigger_time: datetime,
        desktops_to_process_local: List[int],
        try_again_count: int,
        panel_count: int,
        *,
        source_label: str,
        affected_windows: set | None = None,
    ) -> None:
        nonlocal next_allowed_check
        global grace_period_end, pre_cooldown_fingerprints, session_rate_limit_count

        total_indicators = try_again_count + panel_count
        if total_indicators == 0:
            return

        # Update session statistics
        session_rate_limit_count += 1

        # Capture which windows had rate limits before entering cooldown
        if affected_windows:
            pre_cooldown_fingerprints = affected_windows.copy()
        else:
            pre_cooldown_fingerprints = set()

        # Clear stale Try Again tracking since we confirmed a real rate limit
        stale_try_again_windows.clear()

        print(f"\n{'='*70}")
        print(
            f"[{trigger_time}] RATE LIMIT DETECTED ({source_label})!"
        )
        if try_again_count:
            print(f"  Found {try_again_count} 'Try Again' button(s) across active windows")
        if panel_count:
            print(f"  Detected {panel_count} rate limit message panel(s)")
        if pre_cooldown_fingerprints:
            print(f"  Affected windows: {len(pre_cooldown_fingerprints)} (will ignore these during grace period)")
        print(f"  Entering {COOLDOWN_MINUTES}-minute cooldown...")
        print("  Will click any lingering 'Try Again' buttons afterwards")
        print(f"{'='*70}\n")

        next_allowed_check = trigger_time + timedelta(minutes=COOLDOWN_MINUTES)

        # Use cooldown time to process finished and rate-limited panels
        print("  📋 Using cooldown time to check finished and rate-limited panels...")
        all_vs_windows = []
        for desktop_num in desktops_to_process_local:
            if _needs_desktop_switch(desktop_num):
                switch_to_desktop(desktop_num)
                time.sleep(0.3)
            windows = find_all_vscode_windows()
            all_vs_windows.extend(windows)
        
        finished_processed = process_finished_panels(all_vs_windows)
        if finished_processed > 0:
            print(f"  ✓ Processed {finished_processed} finished panel(s)")
        
        rate_limited_processed = process_rate_limited_panels(all_vs_windows)
        if rate_limited_processed > 0:
            print(f"  ✓ Sent 'please continue' to {rate_limited_processed} rate-limited panel(s)")

        cooldown_paused = False
        while datetime.now() < next_allowed_check:
            # Poll for hotkeys during cooldown
            for _ in range(50):  # Poll for 5 seconds
                check_hotkeys_polled()
                if is_paused:
                    cooldown_paused = True
                    break
                time.sleep(0.1)
            if cooldown_paused:
                break
            remaining = (next_allowed_check - datetime.now()).total_seconds()
            minutes = int(remaining // 60)
            seconds = int(remaining % 60)
            print(
                f"\r[{datetime.now()}] Cooldown: {minutes:2d}:{seconds:02d} remaining  ",
                end='',
                flush=True,
            )

        if cooldown_paused:
            print(f"\n[{datetime.now()}] Manual pause detected during cooldown. Holding automation...")
            time.sleep(1)
            return

        print(f"\n\n[{datetime.now()}] Cooldown complete! Checking for lingering 'Try Again' buttons...")
        clicked_after_cooldown, successful_continues = click_try_again_buttons_on_desktops(desktops_to_process_local)
        if is_paused:
            print(f"\n[{datetime.now()}] Manual pause detected while clearing 'Try Again' buttons. Holding automation...")
            time.sleep(1)
            return
        if clicked_after_cooldown == 0:
            print("  No Try Again buttons were present after cooldown.")
        else:
            rate_status = _format_rate_status(datetime.now())
            print(f"  Clicked {clicked_after_cooldown} Try Again button(s), {successful_continues} agents continued. [{rate_status}]")

        # Set grace period - during this time, we'll only trigger on NEW rate limits
        # (i.e., windows that weren't already showing rate limits before cooldown)
        grace_period_end = datetime.now() + timedelta(minutes=POST_COOLDOWN_GRACE_MINUTES)
        print(f"[{datetime.now()}] Rate limit recovery complete. {POST_COOLDOWN_GRACE_MINUTES}-minute grace period active.")
        print(f"  (Will ignore rate limits in previously-affected windows until {grace_period_end.strftime('%H:%M:%S')})\n")
        time.sleep(MIN_SCAN_INTERVAL_SECONDS)

    while True:
        now = datetime.now()
        
        # Poll for hotkeys (more reliable than keyboard library hooks)
        check_hotkeys_polled()
        
        # Check for auto-pause on typing
        if AUTO_PAUSE_ON_TYPING:
            user_active, idle_seconds = detect_recent_user_input(now)

            if user_active:
                if not is_auto_paused:
                    is_auto_paused = True
                    print(f"\n[{now}] ⌨️  Typing detected - auto-paused")
                    if SPEAK_PAUSE_EVENTS:
                        _speak("Auto paused")
                # Keep polling hotkeys while auto-paused
                time.sleep(0.1)
                continue
            elif is_auto_paused:
                is_auto_paused = False
                idle_note = (f" (~{idle_seconds:.1f}s idle)" if idle_seconds is not None else "")
                print(f"[{now}] ✓ Typing idle - resuming automation{idle_note}\n")
                if SPEAK_PAUSE_EVENTS:
                    _speak("Resumed")
        
        # Check if manually paused
        if is_paused:
            print(f"[{now}] Manually paused - press {PAUSE_HOTKEY} to resume...")
            # Keep polling while paused so we can detect resume hotkey
            for _ in range(20):  # Poll for ~2 seconds
                check_hotkeys_polled()
                if not is_paused:
                    break
                time.sleep(0.1)
            continue
        
        # Check if in extra wait period
        if now < extra_wait_until:
            remaining = (extra_wait_until - now).total_seconds()
            print(f"[{now}] Extra wait ({remaining:.0f}s left)...")
            # Keep polling during extra wait
            for _ in range(20):  # Poll for ~2 seconds
                check_hotkeys_polled()
                time.sleep(0.1)
            continue

        # Cooldown logic
        if now < next_allowed_check:
            remaining = (next_allowed_check - now).total_seconds()
            print(f"[{now}] In cooldown ({remaining:.0f}s left)...")
            # Keep polling during cooldown
            for _ in range(50):  # Poll for 5 seconds
                check_hotkeys_polled()
                time.sleep(0.1)
            continue

        # ====================================================================
        # WINDOW SCANNING: Either use cached handles OR switch desktops
        # ====================================================================
        total_allow_clicked = 0
        total_keep_edits_clicked = 0
        total_vscode_windows = 0
        pause_requested_mid_cycle = False

        # Determine scanning strategy
        if USE_CACHED_HANDLES and desktops_list != [0]:
            # CACHED MODE: Scan desktops once, then use cached handles
            # This avoids the 1-2 second desktop switching delay every cycle!
            
            # Refresh cache if needed (every CACHE_REFRESH_INTERVAL_MINUTES)
            if should_refresh_cache(now):
                _refresh_window_cache(desktops_list, force=True)
            
            # Get all windows from cache (no desktop switching!)
            vscode_windows = get_cached_vscode_windows()
            
            if vscode_windows:
                total_vscode_windows = len(vscode_windows)
                
                # Sort by priority (TF first, then Trading, then others)
                vscode_windows = _sort_windows_by_priority(vscode_windows)
                
                # Quick panel state summary
                panel_states = get_panel_states_summary(vscode_windows)
                running_count = panel_states[QuickPanelState.RUNNING]
                waiting_count = panel_states[QuickPanelState.WAITING]
                finished_count = panel_states[QuickPanelState.FINISHED]
                
                state_summary = []
                if running_count > 0:
                    state_summary.append(f"{running_count} RUNNING")
                if waiting_count > 0:
                    state_summary.append(f"{waiting_count} WAITING")
                if finished_count > 0:
                    state_summary.append(f"{finished_count} FINISHED")
                
                if state_summary:
                    _log_verbose(f"  [CACHE] {len(vscode_windows)} window(s): {', '.join(state_summary)}")
                
                # Process windows (no desktop switching needed!)
                rescan_pass = 0
                max_rescan_passes = MAX_DESKTOP_RESCAN_PASSES if MAX_DESKTOP_RESCAN_PASSES > 0 else None
                
                while True:
                    if is_paused:
                        pause_requested_mid_cycle = True
                        break
                    rescan_pass += 1
                    allow_this_pass = 0
                    keep_edits_this_pass = 0

                    for win_idx, vs_win in enumerate(vscode_windows, 1):
                        if is_paused:
                            pause_requested_mid_cycle = True
                            break
                        
                        try:
                            window_title = (vs_win.Name or "Unknown")[:50]
                        except Exception:
                            continue  # Window may have been closed
                        
                        # Quick state check
                        panel_state, has_cancel, has_allow = detect_panel_state_quick(vs_win)
                        
                        if rescan_pass == 1:
                            state_indicator = ""
                            if panel_state == QuickPanelState.RUNNING:
                                state_indicator = " [RUNNING]"
                            elif panel_state == QuickPanelState.WAITING:
                                state_indicator = " [WAITING]"
                            elif panel_state == QuickPanelState.FINISHED:
                                state_indicator = " [FINISHED]"
                            _log_verbose(f"    [{win_idx}/{len(vscode_windows)}] {window_title}...{state_indicator}")
                        
                        # Skip finished panels
                        if panel_state == QuickPanelState.FINISHED:
                            continue
                        
                        # Update panel tracking
                        update_panel_from_window(vs_win)
                        check_for_task_completed(vs_win)
                        
                        # Click buttons
                        clicked_counts, _ = click_all_action_buttons(vs_win)
                        allow_this_pass += clicked_counts['allow']
                        keep_edits_this_pass += clicked_counts['keep_edits']

                    total_allow_clicked += allow_this_pass
                    total_keep_edits_clicked += keep_edits_this_pass
                    session_total_allow_clicks += allow_this_pass
                    session_total_keep_edits_clicks += keep_edits_this_pass

                    if allow_this_pass + keep_edits_this_pass == 0:
                        break  # No buttons found

                    print(f"  Clicked {allow_this_pass + keep_edits_this_pass} button(s) (pass {rescan_pass}). Re-scanning...")

                    if max_rescan_passes and rescan_pass >= max_rescan_passes:
                        break

                    time.sleep(DESKTOP_RESCAN_DELAY_SECONDS)
                    
                    # Refresh window list from cache
                    vscode_windows = get_cached_vscode_windows()
                    if not vscode_windows:
                        break
                    vscode_windows = _sort_windows_by_priority(vscode_windows)
            else:
                # No windows in cache - trigger a refresh
                print(f"[{now}] Cache empty - refreshing...")
                _refresh_window_cache(desktops_list, force=True)
        
        else:
            # LEGACY MODE: Switch desktops each cycle (original behavior)
            # If desktops_list is [0], just check current desktop without switching
            if desktops_list == [0]:
                desktops_to_process = [0]
            else:
                # Build smart desktop order: priority desktop first, then others
                desktops_to_process = []
                other_desktops = [d for d in desktops_list if d != PRIORITY_DESKTOP]
                
                if PRIORITY_DESKTOP in desktops_list:
                    desktops_to_process.append(PRIORITY_DESKTOP)
                desktops_to_process.extend(other_desktops)
            
            # Track which desktop we're on to minimize switches
            current_desktop = None
            
            # SMART SCAN: Check priority desktop first, only move to others when no work found
            for desktop_num in desktops_to_process:
                if is_paused:
                    pause_requested_mid_cycle = True
                    break
                
                desktop_label = "current" if desktop_num == 0 or desktop_num == "current" else str(desktop_num)
                is_priority = (desktop_num == PRIORITY_DESKTOP)
                
                # Check if we should skip this desktop due to consecutive failures
                # Note: _should_skip_desktop only works with numeric IDs (legacy)
                if isinstance(desktop_num, int) and desktop_num > 0 and _should_skip_desktop(desktop_num):
                    failures = desktop_failure_counts.get(desktop_num, 0)
                    cycles = desktop_cycles_since_check.get(desktop_num, 0)
                    remaining = DESKTOP_RECHECK_AFTER_FAILURES - cycles
                    _log_normal(f"  → Skipping {desktop_label} (failed {failures}x, recheck in {remaining} cycles)")
                    continue
                
                # Switch to desktop if needed
                if _needs_desktop_switch(desktop_num) and current_desktop != desktop_num:
                    priority_note = " [PRIORITY]" if is_priority else ""
                    _log_normal(f"  → Switching to {desktop_label}{priority_note}...")
                    switch_to_desktop(desktop_num)
                    current_desktop = desktop_num
                    time.sleep(0.5)  # Reduced wait - pyvda is faster
                
                # Check for VS Code windows on this desktop with retry
                # Retry up to 3 times with short waits if no windows found
                vscode_windows = []
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    vscode_windows = find_all_vscode_windows()
                    if vscode_windows:
                        break
                    if _needs_desktop_switch(desktop_num) and attempt < max_retries:
                        wait_time = 1.0 + (attempt * 0.5)  # 1.5s, 2s waits
                        _log_verbose(f"  ⚠ Retry {attempt}/{max_retries}: No windows on {desktop_label}, waiting {wait_time}s...")
                        time.sleep(wait_time)
                
                if not vscode_windows:
                    if _needs_desktop_switch(desktop_num):
                        _log_normal(f"  ⚠ No VS Code windows found on {desktop_label} (skipping)")
                        if isinstance(desktop_num, int):
                            _record_desktop_result(desktop_num, found_windows=False)
                    continue

                # Success - record and reset failure count
                if isinstance(desktop_num, int):
                    _record_desktop_result(desktop_num, found_windows=True)
                total_vscode_windows += len(vscode_windows)
                
                # Sort windows by priority (TF first, then Trading, then others)
                vscode_windows = _sort_windows_by_priority(vscode_windows)
                
                # Quick panel state check - show summary and filter to active/waiting panels
                panel_states = get_panel_states_summary(vscode_windows)
                running_count = panel_states[QuickPanelState.RUNNING]
                waiting_count = panel_states[QuickPanelState.WAITING]
                finished_count = panel_states[QuickPanelState.FINISHED]
                
                state_summary = []
                if running_count > 0:
                    state_summary.append(f"{running_count} RUNNING")
                if waiting_count > 0:
                    state_summary.append(f"{waiting_count} WAITING")
                if finished_count > 0:
                    state_summary.append(f"{finished_count} FINISHED")
                
                if state_summary:
                    _log_verbose(f"  Found {len(vscode_windows)} VS Code window(s) on {desktop_label}: {', '.join(state_summary)}")
                else:
                    _log_verbose(f"  Found {len(vscode_windows)} VS Code window(s) on {desktop_label}")

                desktop_clicked_any = False  # Track if we clicked anything on this desktop
                rescan_pass = 0
                max_rescan_passes = (
                    MAX_DESKTOP_RESCAN_PASSES if MAX_DESKTOP_RESCAN_PASSES > 0 else None
                )
                while True:
                    if is_paused:
                        pause_requested_mid_cycle = True
                        break
                    rescan_pass += 1
                    allow_this_pass = 0
                    keep_edits_this_pass = 0

                    # Process each VS Code window on this desktop
                    for win_idx, vs_win in enumerate(vscode_windows, 1):
                        if is_paused:
                            pause_requested_mid_cycle = True
                            break
                        window_title = (vs_win.Name or "Unknown")[:50]
                        
                        # Quick state check - skip FINISHED panels (no Allow button, not running)
                        panel_state, has_cancel, has_allow = detect_panel_state_quick(vs_win)
                        
                        if rescan_pass == 1:
                            state_indicator = ""
                            if panel_state == QuickPanelState.RUNNING:
                                state_indicator = " [RUNNING]"
                            elif panel_state == QuickPanelState.WAITING:
                                state_indicator = " [WAITING]"
                            elif panel_state == QuickPanelState.FINISHED:
                                state_indicator = " [FINISHED]"
                            _log_verbose(f"    [{win_idx}/{len(vscode_windows)}] Checking: {window_title}...{state_indicator}")
                        
                        # Skip finished panels - they have no Allow button and aren't running
                        if panel_state == QuickPanelState.FINISHED:
                            continue  # Nothing to do for finished panels
                        
                        # Update panel tracking state (running status, output changes)
                        update_panel_from_window(vs_win)
                        
                        # Check if a finished panel responded with "task completed"
                        check_for_task_completed(vs_win)
                        
                        clicked_counts, _ = click_all_action_buttons(vs_win)
                        allow_this_pass += clicked_counts['allow']
                        keep_edits_this_pass += clicked_counts['keep_edits']

                        if is_paused:
                            pause_requested_mid_cycle = True
                            break

                    total_allow_clicked += allow_this_pass
                    total_keep_edits_clicked += keep_edits_this_pass
                    
                    # Update session statistics
                    session_total_allow_clicks += allow_this_pass
                    session_total_keep_edits_clicks += keep_edits_this_pass

                    buttons_clicked_this_pass = allow_this_pass + keep_edits_this_pass
                    if buttons_clicked_this_pass > 0:
                        desktop_clicked_any = True
                    
                    if buttons_clicked_this_pass == 0:
                        break  # No buttons found on this scan pass

                    print(
                        f"  Clicked {buttons_clicked_this_pass} button(s) on {desktop_label} (pass {rescan_pass}). "
                        "Re-scanning..."
                    )

                    if max_rescan_passes and rescan_pass >= max_rescan_passes:
                        break
                    
                    # PRIORITY DESKTOP RECHECK: On non-priority desktops, periodically return
                    # to priority desktop to prevent starvation when non-priority has continuous work
                    if (not is_priority and PRIORITY_RECHECK_INTERVAL_PASSES > 0 
                        and rescan_pass % PRIORITY_RECHECK_INTERVAL_PASSES == 0 
                        and PRIORITY_DESKTOP in desktops_list):
                        print(f"  → Checking priority desktop {PRIORITY_DESKTOP} (every {PRIORITY_RECHECK_INTERVAL_PASSES} passes)...")
                        switch_to_desktop(PRIORITY_DESKTOP)
                        time.sleep(1.0)
                        
                        # Scan priority desktop thoroughly
                        priority_windows = find_all_vscode_windows()
                        if priority_windows:
                            priority_windows = _sort_windows_by_priority(priority_windows)
                            priority_pass = 0
                            while True:
                                priority_pass += 1
                                priority_clicked_this_pass = 0
                                for vs_win in priority_windows:
                                    if is_paused:
                                        pause_requested_mid_cycle = True
                                        break
                                    clicked_counts, _ = click_all_action_buttons(vs_win)
                                    priority_allow = clicked_counts['allow']
                                    priority_keep = clicked_counts['keep_edits']
                                    priority_clicked_this_pass += priority_allow + priority_keep
                                    if priority_allow > 0 or priority_keep > 0:
                                        total_allow_clicked += priority_allow
                                        total_keep_edits_clicked += priority_keep
                                        session_total_allow_clicks += priority_allow
                                        session_total_keep_edits_clicks += priority_keep
                                
                                if priority_clicked_this_pass == 0:
                                    break  # No more buttons on priority desktop
                                print(f"  ✓ Clicked {priority_clicked_this_pass} button(s) on priority desktop {PRIORITY_DESKTOP} (pass {priority_pass})")
                                
                                # Limit priority rescan passes during mid-cycle check
                                if priority_pass >= 3:
                                    break
                                
                                time.sleep(DESKTOP_RESCAN_DELAY_SECONDS)
                                priority_windows = find_all_vscode_windows()
                                if not priority_windows:
                                    break
                                priority_windows = _sort_windows_by_priority(priority_windows)
                        
                        # Return to the non-priority desktop to continue scanning
                        print(f"  → Returning to {desktop_label}...")
                        switch_to_desktop(desktop_num)
                        current_desktop = desktop_num
                        time.sleep(1.0)

                    time.sleep(DESKTOP_RESCAN_DELAY_SECONDS)

                    # RETRY LOGIC: UI tree can be temporarily invalid after clicking
                    # Retry up to 3 times with increasing waits if no windows found
                    vscode_windows = []
                    for rescan_attempt in range(1, 4):
                        vscode_windows = find_all_vscode_windows()
                        if vscode_windows:
                            break
                        if rescan_attempt < 3:
                            wait_time = 0.5 * rescan_attempt  # 0.5s, 1.0s waits
                            _log_verbose(f"  ⚠ Rescan attempt {rescan_attempt}/3: No windows found, waiting {wait_time}s...")
                            time.sleep(wait_time)
                    
                    if not vscode_windows:
                        # PRIORITY DESKTOP PERSISTENCE: If we clicked buttons on the priority desktop
                        # but now can't find windows, don't give up easily - try harder
                        if is_priority and desktop_clicked_any:
                            _log_normal(f"  ⚠ Priority desktop {desktop_num}: Lost windows after clicking. Trying harder...")
                            time.sleep(2.0)  # Longer wait for UI to stabilize
                            
                            # Try one more time with even longer timeout
                            vscode_windows = find_all_vscode_windows(timeout=1.0)
                            if vscode_windows:
                                _log_normal(f"  ✓ Recovered {len(vscode_windows)} window(s) on priority desktop")
                                vscode_windows = _sort_windows_by_priority(vscode_windows)
                                continue  # Continue the while loop with recovered windows
                            
                            # Still no windows - maybe desktop position got confused. Force resync.
                            _log_normal("  ⚠ Desktop position may be wrong. Forcing resync...")
                            global _desktop_sync_done
                            _desktop_sync_done = False
                            switch_to_desktop(desktop_num, force_sync=True)
                            time.sleep(1.0)
                            vscode_windows = find_all_vscode_windows(timeout=1.0)
                            if vscode_windows:
                                _log_normal(f"  ✓ Recovered {len(vscode_windows)} window(s) after resync")
                                vscode_windows = _sort_windows_by_priority(vscode_windows)
                                continue
                        
                        _log_verbose("  ⚠ No VS Code windows found after rescan attempts, moving on")
                        break
                    vscode_windows = _sort_windows_by_priority(vscode_windows)
                
                if pause_requested_mid_cycle:
                    break
                
                # SMART PRIORITY LOGIC:
                # If we're NOT on the priority desktop and we just finished scanning a non-priority desktop,
                # go back to the priority desktop to check if new Allow buttons appeared there
                if not is_priority and desktop_clicked_any and PRIORITY_DESKTOP in desktops_list:
                    _log_verbose(f"  → Returning to priority desktop {PRIORITY_DESKTOP} to check for new buttons...")
                    switch_to_desktop(PRIORITY_DESKTOP)
                    current_desktop = PRIORITY_DESKTOP
                    time.sleep(1.0)
                    
                    # Quick check on priority desktop
                    priority_windows = find_all_vscode_windows()
                    if priority_windows:
                        priority_windows = _sort_windows_by_priority(priority_windows)
                        for vs_win in priority_windows:
                            if is_paused:
                                pause_requested_mid_cycle = True
                                break
                            clicked_counts, _ = click_all_action_buttons(vs_win)
                            priority_allow = clicked_counts['allow']
                            priority_keep = clicked_counts['keep_edits']
                            if priority_allow > 0 or priority_keep > 0:
                                total_allow_clicked += priority_allow
                                total_keep_edits_clicked += priority_keep
                                session_total_allow_clicks += priority_allow
                                session_total_keep_edits_clicks += priority_keep
                                print(f"  ✓ Clicked {priority_allow + priority_keep} button(s) on priority desktop {PRIORITY_DESKTOP}")

        if pause_requested_mid_cycle:
            print(f"\n[{datetime.now()}] Manual pause detected during button scans. Holding automation...")
            time.sleep(1)
            continue

        # Check if we found any VS Code windows at all
        if total_vscode_windows == 0:
            # Handle no-windows-found loop detection
            force_resync = _handle_no_windows_loop(now)
            if force_resync:
                # Skip the sleep and immediately retry with fresh desktop sync
                continue
            
            print(f"[{now}] No VS Code windows found, sleeping {MIN_SCAN_INTERVAL_SECONDS}s...")
            time.sleep(MIN_SCAN_INTERVAL_SECONDS)
            continue
        
        # Found windows - reset the no-windows loop counter
        _reset_no_windows_loop_counter()
        
        # Report what we clicked
        total_clicked = total_allow_clicked + total_keep_edits_clicked
        rate_status = _format_rate_status(now)
        
        if total_clicked > 0:
            summary = []
            if total_allow_clicked > 0:
                summary.append(f"{total_allow_clicked} Allow")
            if total_keep_edits_clicked > 0:
                summary.append(f"{total_keep_edits_clicked} Keep Edits")
            print(f"[{now}] Clicked {', '.join(summary)} button(s). [{rate_status}]")
        else:
            print(f"[{now}] No action buttons found. [{rate_status}]")
        
        # ====================================================================
        # PANEL TRACKING: Check finished panels for follow-up prompts
        # ====================================================================
        # Only check finished panels when:
        # 1. No Allow buttons found on live panels (total_clicked == 0), OR
        # 2. We have remaining rate limit capacity and no urgent work
        
        # Update panel statuses (transition LIVE -> IDLE -> FINISHED)
        tracker = get_tracker()
        tracker.update_panel_status()
        
        # Calculate remaining clicks before rate limit
        remaining_clicks = MAX_ALLOWS_PER_HOUR - len(allow_events)
        
        # Should we check finished panels?
        live_work_found = total_clicked > 0
        if should_check_finished_panels(remaining_clicks, live_work_found):
            # Collect all VS Code windows for finished panel processing
            if USE_CACHED_HANDLES and desktops_list != [0]:
                # Use cached handles - no desktop switching!
                all_vs_windows = get_cached_vscode_windows()
            else:
                # Legacy mode - switch desktops to collect windows
                all_vs_windows = []
                desktops_for_scan = desktops_list if desktops_list != [0] else [0]
                for desktop_num in desktops_for_scan:
                    if _needs_desktop_switch(desktop_num):
                        switch_to_desktop(desktop_num)
                        time.sleep(0.3)
                    windows = find_all_vscode_windows()
                    all_vs_windows.extend(windows)
            
            # Process finished panels (send follow-up prompts)
            finished_processed = process_finished_panels(all_vs_windows)
            if finished_processed > 0:
                print(f"[{datetime.now()}] Processed {finished_processed} finished panel(s) with follow-up prompts")
            
            # Process rate limited panels (send "please continue")
            rate_limited_processed = process_rate_limited_panels(all_vs_windows)
            if rate_limited_processed > 0:
                print(f"[{datetime.now()}] Sent 'please continue' to {rate_limited_processed} rate-limited panel(s)")
        
        # Periodically print tracker status (every 10 minutes)
        global last_tracker_status_time
        if (datetime.now() - last_tracker_status_time).total_seconds() > 600:
            print_tracker_status()
            last_tracker_status_time = datetime.now()

        last_cycle_metrics.update(
            {
                "total_vscode_windows": total_vscode_windows,
                "allow_clicked_cycle": total_allow_clicked,
                "keep_edits_clicked_cycle": total_keep_edits_clicked,
            }
        )

        log_allow_metrics(
            datetime.now(),
            total_vscode_windows=total_vscode_windows,
            allow_clicked_cycle=total_allow_clicked,
            keep_edits_clicked_cycle=total_keep_edits_clicked,
        )

        check_for_master = datetime.now()
        if should_trigger_master_agent(check_for_master):
            trigger_master_agent_prompt_generation(check_for_master)

        # Increment desktop cycle counters for reliability tracking
        _increment_desktop_cycles()

        # Smart rate-based waiting:
        # - If under rate limit: check immediately (with small minimum delay)
        # - If at rate limit: wait until oldest event expires from 60-min window
        wait_seconds = get_rate_limit_wait_seconds(datetime.now())
        if wait_seconds > 0:
            print(f"  ⏳ Rate limit reached ({rate_status}). Waiting {wait_seconds:.0f}s for slot to open...")
            
            # We have idle time - process finished/rate-limited panels now
            print("  📋 Using wait time to check finished and rate-limited panels...")
            if USE_CACHED_HANDLES and desktops_list != [0]:
                # Use cached handles - no desktop switching!
                all_vs_windows = get_cached_vscode_windows()
            else:
                # Legacy mode - switch desktops to collect windows
                all_vs_windows = []
                desktops_for_scan = desktops_list if desktops_list != [0] else [0]
                for desktop_num in desktops_for_scan:
                    if _needs_desktop_switch(desktop_num):
                        switch_to_desktop(desktop_num)
                        time.sleep(0.3)
                    windows = find_all_vscode_windows()
                    all_vs_windows.extend(windows)
            
            finished_processed = process_finished_panels(all_vs_windows)
            if finished_processed > 0:
                print(f"  ✓ Processed {finished_processed} finished panel(s)")
            
            rate_limited_processed = process_rate_limited_panels(all_vs_windows)
            if rate_limited_processed > 0:
                print(f"  ✓ Sent 'please continue' to {rate_limited_processed} rate-limited panel(s)")
            
            # Poll for hotkeys during the wait
            wait_end = datetime.now() + timedelta(seconds=wait_seconds)
            while datetime.now() < wait_end:
                check_hotkeys_polled()
                if is_paused:
                    break
                # Check for typing/auto-pause
                if AUTO_PAUSE_ON_TYPING:
                    user_active, _ = detect_recent_user_input(datetime.now())
                    if user_active:
                        break
                time.sleep(0.5)
        else:
            # Under rate limit - still wait a small minimum to avoid CPU thrashing
            time.sleep(MIN_SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    shutdown_reason = "clean exit"
    try:
        main()
    except KeyboardInterrupt:
        shutdown_reason = "KeyboardInterrupt"
        print(f"\n[{datetime.now()}] KeyboardInterrupt received. Shutting down...")
    except Exception as exc:
        shutdown_reason = f"crash ({exc})"
        print(f"\n[{datetime.now()}] Fatal error: {exc}")
        raise
    finally:
        flush_metrics_on_exit(shutdown_reason)
