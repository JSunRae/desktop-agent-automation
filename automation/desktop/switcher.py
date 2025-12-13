"""
Desktop switching using Windows virtual desktops.

Uses pyvda library for direct desktop switching by name (recommended).
Falls back to Win+Ctrl+Arrow keys for numeric desktop IDs.

Using desktop names is more reliable as the order doesn't change.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

import keyboard
import pyvda

from automation.config import (
    MAX_DESKTOPS_TO_SCAN,
    DESKTOP_SCAN_WAIT,
    VSCODE_TITLE_SUFFIX,
    DESKTOPS_TO_CHECK,
)
from automation.core.logging import log_verbose, log_normal


# ============================================================================
# SWITCH VERIFICATION CONSTANTS/METRICS
# ============================================================================

SWITCH_VERIFICATION_DELAY = 0.5  # seconds
MAX_SWITCH_ATTEMPTS = 3

_switch_metrics: Dict[str, int] = {
    "attempts": 0,
    "success": 0,
    "failures": 0,
    "retries": 0,
}


# ============================================================================
# GLOBAL STATE
# ============================================================================

# Track current desktop for optimized switching (legacy numeric mode)
_current_desktop: int = 1  # Assume we start on desktop 1 (will sync on first switch)
_desktop_sync_done: bool = False  # Have we synced to a known position?

# Cached desktops list (populated on first call)
_desktops_to_check_cache: List[Union[int, str]] | None = None


# ============================================================================
# STATE ACCESSORS
# ============================================================================

def get_current_desktop() -> int:
    """Get the current desktop number (1-based)."""
    return _current_desktop


def is_desktop_sync_done() -> bool:
    """Check if desktop position has been synced."""
    return _desktop_sync_done


def reset_desktop_sync() -> None:
    """Reset desktop sync state to force re-sync on next switch."""
    global _desktop_sync_done
    _desktop_sync_done = False


# ============================================================================
# SWITCH STATUS HELPERS
# ============================================================================

def _format_desktop_label(desktop_id: Union[int, str]) -> str:
    """Return a compact label for logging desktop identifiers."""
    return desktop_id if isinstance(desktop_id, str) else f"desktop #{desktop_id}"


def _log_switch_status(status: str, target_label: str, attempt: int, detail: str) -> None:
    """Emit a normalized log entry with running metrics."""
    metrics_snapshot = (
        f"attempts={_switch_metrics['attempts']} "
        f"success={_switch_metrics['success']} "
        f"failures={_switch_metrics['failures']} "
        f"retries={_switch_metrics['retries']}"
    )
    log_normal(
        f"  [DESKTOP] {status} -> {target_label} "
        f"(attempt {attempt}/{MAX_SWITCH_ATTEMPTS}) {detail} | {metrics_snapshot}"
    )


def _verify_switch_state(target: Union[int, str]) -> Tuple[bool, str]:
    """Confirm we actually landed on the target desktop."""
    if isinstance(target, str):
        current_name = _get_current_desktop_name()
        if current_name == target:
            return True, f"current='{current_name}'"
        return False, f"expected='{target}', current='{current_name or 'unknown'}'"
    # Numeric desktop verification falls back to our tracked counter.
    detail = f"tracked={_current_desktop}"
    if _current_desktop == target:
        return True, detail
    try:
        current = pyvda.VirtualDesktop.current()
        current_name = current.name if current else None
        detail = f"{detail}, current_name='{current_name or 'unknown'}'"
    except Exception:
        detail = f"{detail}, current_name='error'"
    return False, detail


def needs_desktop_switch(desktop_num: int | str) -> bool:
    """
    Check if we need to switch to access this desktop.
    
    Args:
        desktop_num: Desktop number, 0, or "current"
        
    Returns:
        False if desktop_num is 0 or "current" (no switch needed)
        True if desktop_num is a specific desktop number
    """
    if desktop_num == 0 or desktop_num == "current":
        return False
    return True


def get_desktops_to_check() -> List[Union[int, str]]:
    """
    Get the list of desktops to check for VS Code windows.
    
    Uses DESKTOPS_TO_CHECK from config:
    - If [0], returns [0] (check current desktop only)
    - If "auto", detects desktops with VS Code windows
    - If ["TF", "Trading"], uses desktop names with pyvda
    - Otherwise, returns the configured list
    
    Returns:
        List of desktop names or numbers to check
    """
    global _desktops_to_check_cache
    
    if _desktops_to_check_cache is not None:
        return _desktops_to_check_cache
    
    if DESKTOPS_TO_CHECK == [0]:
        _desktops_to_check_cache = [0]
    elif DESKTOPS_TO_CHECK == "auto":
        _desktops_to_check_cache = detect_desktops_with_vscode()
    elif isinstance(DESKTOPS_TO_CHECK, list):
        if "auto" in DESKTOPS_TO_CHECK:
            base = [d for d in DESKTOPS_TO_CHECK if d != "auto"]
            auto_list = detect_desktops_with_vscode()
            # Preserve base order (e.g., TF then Trading) and append any auto-detected desktops not already listed
            combined: List[Union[int, str]] = base + [d for d in auto_list if d not in base]
            _desktops_to_check_cache = combined if combined else [0]
        else:
            _desktops_to_check_cache = list(DESKTOPS_TO_CHECK)
    else:
        _desktops_to_check_cache = [0]
    
    return _desktops_to_check_cache


# ============================================================================
# PYVDA DESKTOP HELPERS
# ============================================================================

def _get_desktop_by_name(name: str) -> Optional[pyvda.VirtualDesktop]:
    """
    Find a virtual desktop by its name using pyvda.
    
    Args:
        name: Desktop name to search for (e.g., "TF", "Trading")
        
    Returns:
        VirtualDesktop object if found, None otherwise
    """
    try:
        desktops = pyvda.get_virtual_desktops()
        for desktop in desktops:
            if desktop.name == name:
                return desktop
    except Exception as e:
        log_verbose(f"  Error getting desktops: {e}")
    return None


def _get_current_desktop_name() -> Optional[str]:
    """
    Get the name of the current virtual desktop.
    
    Returns:
        Desktop name or None if unable to determine
    """
    try:
        current = pyvda.VirtualDesktop.current()
        return current.name if current else None
    except Exception:
        return None


# ============================================================================
# DESKTOP SWITCHING
# ============================================================================

def switch_to_desktop(desktop_id: Union[int, str], force_sync: bool = False) -> None:
    """
    Switch to a specific virtual desktop (Windows 10/11).
    
    Supports two modes:
    - String name (e.g., "TF"): Uses pyvda for direct switching (recommended)
    - Integer number: Falls back to Win+Ctrl+Arrow key navigation
    
    Args:
        desktop_id: Desktop name (str) or 1-based number (int)
        force_sync: If True and using numeric mode, sync to desktop 1 first
    """
    global _current_desktop, _desktop_sync_done
    
    # If it's a string name, use pyvda for direct switching
    if isinstance(desktop_id, str):
        _switch_to_desktop_by_name(desktop_id)
        return
    
    # Legacy numeric switching with keyboard
    desktop_number = desktop_id
    
    try:
        # Release any held modifier keys first to avoid interference
        keyboard.release('ctrl')
        keyboard.release('shift')
        keyboard.release('alt')
        keyboard.release('win')
        time.sleep(0.15)
        
        # If we don't know where we are, sync to desktop 1 first (one-time)
        if not _desktop_sync_done or force_sync:
            log_verbose("  📍 Syncing desktop position (going to desktop 1)...")
            for _ in range(MAX_DESKTOPS_TO_SCAN):
                keyboard.send('win+ctrl+left')
                time.sleep(0.15)
            _current_desktop = 1
            _desktop_sync_done = True
            time.sleep(0.8)
        
        # If already on target, no switch needed
        if _current_desktop == desktop_number:
            return
        
        # Calculate direction and steps needed
        if desktop_number > _current_desktop:
            # Move right
            steps = desktop_number - _current_desktop
            for _ in range(steps):
                keyboard.send('win+ctrl+right')
                time.sleep(0.2)
        elif desktop_number < _current_desktop:
            # Move left
            steps = _current_desktop - desktop_number
            for _ in range(steps):
                keyboard.send('win+ctrl+left')
                time.sleep(0.2)
        
        _current_desktop = desktop_number
        
        # Wait for UI tree to update after switch
        time.sleep(1.5)
        
        # Try to activate a window on this desktop to ensure UI tree is rendered
        _activate_first_vscode_window()
        
    except Exception as e:
        print(f"[{datetime.now()}] Error switching desktop: {e}")


def _switch_to_desktop_by_name(name: str) -> None:
    """
    Switch to a desktop by name using pyvda.
    
    Args:
        name: Desktop name (e.g., "TF", "Trading")
    """
    try:
        # Check if already on target desktop
        current_name = _get_current_desktop_name()
        if current_name == name:
            log_verbose(f"  Already on desktop '{name}'")
            return
        
        # Find and switch to target desktop
        target_desktop = _get_desktop_by_name(name)
        if target_desktop:
            log_verbose(f"  Switching to desktop '{name}'...")
            target_desktop.go()
            time.sleep(0.5)  # Wait for switch to complete
            
            # Verify switch succeeded
            new_current = _get_current_desktop_name()
            if new_current == name:
                log_verbose(f"  ✓ Now on desktop '{name}'")
            else:
                log_normal(f"  ⚠ Switch may have failed: expected '{name}', got '{new_current}'")
            
            # Try to activate a window to force UI tree update
            _activate_first_vscode_window()
        else:
            log_normal(f"  ⚠ Desktop '{name}' not found!")
            # List available desktops for debugging
            try:
                desktops = pyvda.get_virtual_desktops()
                names = [d.name for d in desktops]
                log_normal(f"  Available desktops: {names}")
            except Exception:
                pass
                
    except Exception as e:
        print(f"[{datetime.now()}] Error switching to desktop '{name}': {e}")


def _activate_first_vscode_window() -> None:
    """Try to activate the first VS Code window to force UI rendering."""
    try:
        # Import here to avoid circular dependency
        from automation.ui.vscode_windows import find_all_vscode_windows
        from automation.ui.window_utils import set_foreground_window
        
        windows = find_all_vscode_windows(timeout=0.3)
        if windows:
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


def detect_desktops_with_vscode() -> List[int]:
    """
    Auto-detect which virtual desktops have VS Code windows open.
    
    Returns:
        List of desktop numbers (1-based) that have VS Code, or [0] for current only.
    """
    # Import here to avoid circular dependency
    from automation.ui.vscode_windows import find_all_vscode_windows
    
    print(f"[{datetime.now()}] Scanning desktops for VS Code windows...")
    log_verbose(f"  Note: This will cycle through up to {MAX_DESKTOPS_TO_SCAN} desktops...")
    desktops_with_vscode: List[int] = []
    original_desktop = None
    
    try:
        # Check current desktop first
        current_vscode = find_all_vscode_windows(timeout=0.5)
        if current_vscode:
            log_verbose(f"  ✓ Current desktop: Found {len(current_vscode)} VS Code window(s)")
        
        # Go to desktop 1
        log_verbose("  Navigating to desktop 1...")
        for _ in range(MAX_DESKTOPS_TO_SCAN):
            keyboard.send('win+ctrl+left')
            time.sleep(0.15)
        time.sleep(DESKTOP_SCAN_WAIT)
        
        # Scan each desktop
        for desktop_num in range(1, MAX_DESKTOPS_TO_SCAN + 1):
            vscode_windows = find_all_vscode_windows(timeout=0.5)
            
            if vscode_windows:
                desktops_with_vscode.append(desktop_num)
                log_verbose(f"  ✓ Desktop {desktop_num}: Found {len(vscode_windows)} VS Code window(s)")
                if original_desktop is None:
                    original_desktop = desktop_num
            else:
                log_verbose(f"    Desktop {desktop_num}: No VS Code windows")
            
            # Move to next desktop
            if desktop_num < MAX_DESKTOPS_TO_SCAN:
                keyboard.send('win+ctrl+right')
                time.sleep(DESKTOP_SCAN_WAIT)
            
            # Stop if no VS Code found for 4 consecutive desktops
            if len(desktops_with_vscode) > 0 and desktop_num > desktops_with_vscode[-1] + 4:
                log_verbose(f"  No more VS Code windows found after desktop {desktops_with_vscode[-1]}")
                break
        
        if not desktops_with_vscode:
            print("  ⚠ No VS Code windows found on any desktop during scan!")
            log_normal("  Recommendation: Set DESKTOPS_TO_CHECK = [0] to work on current desktop only")
            return [0]
        
        print(f"[{datetime.now()}] Auto-detected desktops: {desktops_with_vscode}")
        
        # Return to the first desktop with VS Code
        if original_desktop:
            log_verbose(f"  Returning to desktop {original_desktop}...")
            switch_to_desktop(original_desktop)
        
        return desktops_with_vscode
        
    except Exception as e:
        print(f"[{datetime.now()}] Error during desktop detection: {e}")
        print("  Falling back to current desktop only.")
        return [0]
