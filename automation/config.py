"""
Unified Configuration Module for Desktop Agent Automation.

This module centralizes all configuration from:
- Environment variables (.env file)
- Hardcoded defaults
- Runtime feature toggles

Configuration categories:
- Timing: cooldowns, thresholds, intervals
- Rate limiting: max allows per hour, buffer times
- Desktop: which desktops to check, priority desktop
- Hotkeys: pause, extra wait key combinations
- Features: toggles for optional behaviors
- Paths: log files, state persistence
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_DOTENV_PATH = REPO_ROOT / ".env"

# Load only the repository root .env so parent-directory dotenv files do not
# accidentally override runtime secrets for live automation.
if REPO_DOTENV_PATH.exists():
    load_dotenv(REPO_DOTENV_PATH, override=False)


# ============================================================================
# WIN32 API CONSTANTS
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
# TIMING CONFIGURATION
# ============================================================================

# Cooldown after rate limit detection
COOLDOWN_MINUTES = 10

# Grace period after cooldown where we ignore pre-existing rate limit indicators
POST_COOLDOWN_GRACE_MINUTES = 5

# Additional wait when pause key is pressed
EXTRA_PAUSE_SECONDS = 30

# Minimum time between scans (prevents CPU thrashing)
MIN_SCAN_INTERVAL_SECONDS = 0.5

# Delay between re-check passes on a desktop
DESKTOP_RESCAN_DELAY_SECONDS = 0.5


# ============================================================================
# RATE LIMITING CONFIGURATION
# ============================================================================

# Max Allow clicks per 60-minute rolling window
# Safe: 50-60, Risky: 100+
MAX_ALLOWS_PER_HOUR = 80

# Extra seconds to wait after oldest event expires (safety margin)
RATE_LIMIT_BUFFER_SECONDS = 5

# After clicking on a desktop, re-check this many times max before switching
# Set to 0 for unlimited passes until no buttons remain
MAX_DESKTOP_RESCAN_PASSES = 0

# Return to priority desktop every N passes on non-priority desktops
# Set to 0 to disable
PRIORITY_RECHECK_INTERVAL_PASSES = 5


# ============================================================================
# RATE LIMIT DETECTION CONFIGURATION  
# ============================================================================

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

# Rate limit verification configuration
RATE_LIMIT_VERIFY_CLICKS = int(os.environ.get("RATE_LIMIT_VERIFY_CLICKS", "1"))
RATE_LIMIT_VERIFY_WAIT_SECONDS = float(os.environ.get("RATE_LIMIT_VERIFY_WAIT_SECONDS", "1.5"))
RATE_LIMIT_ACTIVITY_CHECK_INTERVAL = float(os.environ.get("RATE_LIMIT_ACTIVITY_CHECK_INTERVAL", "0.3"))


# ============================================================================
# DESKTOP CONFIGURATION
# ============================================================================

# Set to [0] to only check current desktop (no switching)
# Set to "auto" to automatically detect which desktops have VS Code
# Set to ["TF", "Trading"] to use desktop names with pyvda (recommended)
# Set to [1, 2, 3] to manually specify desktops by number (legacy)
# Default: keep TF/Trading priority and append any other VS Code desktops automatically
DESKTOPS_TO_CHECK: Union[str, List[Union[int, str]]] = ["TF", "Trading", "auto"]

# Priority desktop - check this first, return here after other desktops
# Can be a name ("TF") or number (1)
PRIORITY_DESKTOP: Union[int, str] = "TF"

# Max number of desktops to scan during auto-detection
MAX_DESKTOPS_TO_SCAN = 10

# Seconds to wait after switching during scan
DESKTOP_SCAN_WAIT = 2

# Skip a desktop after this many consecutive "no windows" cycles
DESKTOP_MAX_CONSECUTIVE_FAILURES = 3

# Re-check a failed desktop after this many cycles
DESKTOP_RECHECK_AFTER_FAILURES = 5


# ============================================================================
# NO-WINDOWS LOOP DETECTION
# ============================================================================

# Warn with speech after this many consecutive "no windows found" cycles
NO_WINDOWS_LOOP_WARN_THRESHOLD = 10

# Force desktop resync after this many cycles
NO_WINDOWS_LOOP_FORCE_RESYNC_AFTER = 20

# Seconds between repeated speech warnings
NO_WINDOWS_LOOP_SPEAK_INTERVAL = 30


# ============================================================================
# WINDOW CACHING CONFIGURATION
# ============================================================================

# Use cached handles instead of switching desktops (recommended)
USE_CACHED_HANDLES = True

# Refresh cache every N minutes to find new windows
CACHE_REFRESH_INTERVAL_MINUTES = 2

# Remove windows not seen for this long
CACHE_STALE_THRESHOLD_MINUTES = 10


# ============================================================================
# ZERO-BOUNDS BUTTON TRACKING
# ============================================================================

# Retry buttons with zero bounds after this many minutes
ZERO_BOUNDS_IGNORE_MINUTES = 2


# ============================================================================
# FOCUS TERMINAL DEDUPLICATION
# ============================================================================

FOCUS_TERMINAL_DEDUPE_MINUTES = int(os.environ.get("FOCUS_TERMINAL_DEDUPE_MINUTES", "30"))
FOCUS_TERMINAL_SPEAK_ALERTS = os.environ.get("FOCUS_TERMINAL_SPEAK_ALERTS", "true").lower() == "true"


# ============================================================================
# STALE TRY AGAIN TRACKING
# ============================================================================

# After seeing Try Again in same window this long without agent activity, consider it stale
STALE_TRY_AGAIN_IGNORE_AFTER_MINUTES = 5

# Cooldown duration (in minutes) when rate limit is detected via Try Again button
# After clicking Allow, we wait 2s to check if Try Again appears - if so, we're rate limited
TRY_AGAIN_COOLDOWN_MINUTES = int(os.environ.get("TRY_AGAIN_COOLDOWN_MINUTES", "5"))
TRY_AGAIN_WEEKLY_RETRY_LOCAL_HOUR = int(os.environ.get("TRY_AGAIN_WEEKLY_RETRY_LOCAL_HOUR", "1"))
TRY_AGAIN_WEEKLY_RETRY_INTERVAL_HOURS = int(os.environ.get("TRY_AGAIN_WEEKLY_RETRY_INTERVAL_HOURS", "4"))


# ============================================================================
# SEND TO INACTIVE PANELS CONFIGURATION
# ============================================================================

# Feature toggle: Send text to inactive/finished panels
# DISABLED BY DEFAULT - This feature sends follow-up prompts to finished/rate-limited panels
# Set to True only after thorough testing to avoid accidental sends
# WARNING: When enabled, this can send unwanted text to panels, causing cost issues
ENABLE_SEND_TO_INACTIVE_PANELS = os.environ.get("ENABLE_SEND_TO_INACTIVE_PANELS", "false").lower() == "true"

# Feature toggle: Use clipboard-based methods to read chat input text
# DISABLED BY DEFAULT - This uses SendKeys which can accidentally type characters
# when timing/focus is off, causing ^ characters to appear in chat
# WARNING: When enabled, may type garbage characters into chat panels
ENABLE_CLIPBOARD_TEXT_READING = os.environ.get("ENABLE_CLIPBOARD_TEXT_READING", "false").lower() == "true"

# Feature toggle: Use VS Code toast notifications as a fast path to focus the right panel
# and attempt approval clicks before running a full desktop scan.
ENABLE_VSCODE_TOAST_SHORTCUT = os.environ.get("ENABLE_VSCODE_TOAST_SHORTCUT", "true").lower() == "true"

# Feature toggle: Drive finished panels by sending follow-ups, keeping edits, and seeding new prompts
# ENABLED BY DEFAULT to support automated seeding logic.
ENABLE_FINISHED_PANEL_FOLLOWUPS = os.environ.get("ENABLE_FINISHED_PANEL_FOLLOWUPS", "true").lower() == "true"

# Feature toggle: Handle "OK" confirmation dialogs after clicking Keep Edits
# DISABLED BY DEFAULT - Enable only if your VS Code version shows these dialogs
ENABLE_KEEP_EDITS_CONFIRMATION = os.environ.get("ENABLE_KEEP_EDITS_CONFIRMATION", "false").lower() == "true"

# Feature toggle: Skip clicking "Keep" and "Keep Edits" buttons
# ENABLED BY DEFAULT - "Keep" buttons are lower priority than "Allow" and "Try Again"
# Set to "false" to re-enable Keep button clicking if needed
IGNORE_KEEP_BUTTONS = os.environ.get("IGNORE_KEEP_BUTTONS", "true").lower() == "false"

# Feature toggle: Retry opening new chat if it fails
# ENABLED BY DEFAULT - Enable to improve robustness against UI lag
ENABLE_NEW_CHAT_RETRY = os.environ.get("ENABLE_NEW_CHAT_RETRY", "true").lower() == "true"

# Feature toggle: Catch and log errors during finished panel processing instead of crashing
# ENABLED BY DEFAULT - Enable for long-running stability
ENABLE_ROBUST_PANEL_PROCESSING = os.environ.get("ENABLE_ROBUST_PANEL_PROCESSING", "true").lower() == "true"

# Feature toggle: Periodically run panel_state.json health checks while scanning
ENABLE_PANEL_HEALTH_CHECK_SCHEDULING = os.environ.get("ENABLE_PANEL_HEALTH_CHECK_SCHEDULING", "false").lower() == "true"
PANEL_HEALTH_CHECK_INTERVAL_MINUTES = int(os.environ.get("PANEL_HEALTH_CHECK_INTERVAL_MINUTES", "60"))
PANEL_HEALTH_STALE_DAYS = int(os.environ.get("PANEL_HEALTH_STALE_DAYS", "7"))

# Feature toggle: Periodically run panel inspection suites while automation is active.
# Default is safe/off. When enabled, panel_inspect runs dry-run unless --live-click
# is passed explicitly in direct command usage.
ENABLE_PANEL_INSPECT_SCHEDULING = os.environ.get("ENABLE_PANEL_INSPECT_SCHEDULING", "false").lower() == "true"
PANEL_INSPECT_INTERVAL_MINUTES = int(os.environ.get("PANEL_INSPECT_INTERVAL_MINUTES", "30"))
PANEL_INSPECT_TIMEOUT_SECONDS = int(os.environ.get("PANEL_INSPECT_TIMEOUT_SECONDS", "120"))
PANEL_INSPECT_SCHEDULE_SUITE = os.environ.get("PANEL_INSPECT_SCHEDULE_SUITE", "scan").strip().lower()
PANEL_INSPECT_TARGET_REPO = os.environ.get("PANEL_INSPECT_TARGET_REPO", "desktop-agent-automation").strip()

# Dry-run mode for finished panel follow-ups (log only, no UI sends)
FINISHED_PANEL_DRY_RUN = os.environ.get("FINISHED_PANEL_DRY_RUN", "false").lower() == "true"

# Where to read the prompt batch used to seed new chats when a panel is finished
FINISHED_PANEL_PROMPT_PATH = Path(os.environ.get("FINISHED_PANEL_PROMPT_PATH", "tasks/generated_prompts/latest.txt"))

# If true, a finished-panel miss can request an immediate feed refresh instead of waiting
# for the next periodic discovery interval.
ENABLE_ON_DEMAND_FEED_REFRESH = os.environ.get("ENABLE_ON_DEMAND_FEED_REFRESH", "true").lower() == "true"

# If true, repos without a dedicated prompt feed may fall back to FINISHED_PANEL_PROMPT_PATH.
# If false (default), "no assignment" means "skip panel" and do not seed from latest.txt.
FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK = (
    os.environ.get("FINISHED_PANEL_ALLOW_DEFAULT_PROMPT_FALLBACK", "false").lower() == "true"
)

# Shared default for text-only OpenAI coordination tasks. Vision/computer-use
# flows should keep their own model selection because capability support differs.
OPENAI_COORDINATION_MODEL = os.environ.get("OPENAI_COORDINATION_MODEL", "gpt-5.4")

# Desktop auto-allow uses capability-specific vision/computer-use models rather
# than the shared text coordination default.
AUTO_ALLOW_COMPUTER_USE_MODEL = os.environ.get("AUTO_ALLOW_COMPUTER_USE_MODEL", "computer-use-preview")
AUTO_ALLOW_VISION_FALLBACK_MODEL = os.environ.get("AUTO_ALLOW_VISION_FALLBACK_MODEL", "gpt-4o")

# Optional targeted overrides for specific text-only workflows.
HANDOVER_SUMMARY_MODEL = os.environ.get("HANDOVER_SUMMARY_MODEL", OPENAI_COORDINATION_MODEL)
PANEL_CLASSIFICATION_MODEL = os.environ.get("PANEL_CLASSIFICATION_MODEL", OPENAI_COORDINATION_MODEL)

# Finished panel review pipeline configuration
FINISHED_PANEL_REVIEW_MODEL = os.environ.get("FINISHED_PANEL_REVIEW_MODEL", OPENAI_COORDINATION_MODEL)
FINISHED_PANEL_REVIEW_MAX_RETRIES = int(os.environ.get("FINISHED_PANEL_REVIEW_MAX_RETRIES", "3"))
FINISHED_PANEL_REVIEW_BACKOFF_SECONDS = float(os.environ.get("FINISHED_PANEL_REVIEW_BACKOFF_SECONDS", "1.5"))
FINISHED_PANEL_REVIEW_TRANSCRIPT_CHARS = int(os.environ.get("FINISHED_PANEL_REVIEW_TRANSCRIPT_CHARS", "2000"))
FINISHED_PANEL_REVIEW_TEMPERATURE = float(os.environ.get("FINISHED_PANEL_REVIEW_TEMPERATURE", "0.25"))

# Workstream coordination and chat lifecycle controls.
ENABLE_WORKSTREAM_COORDINATION = os.environ.get("ENABLE_WORKSTREAM_COORDINATION", "true").lower() == "true"
WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT = int(os.environ.get("WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT", "6000"))
WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT = int(os.environ.get("WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT", "10000"))
WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT = int(os.environ.get("WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT", "3500"))
WORKSTREAM_CONDENSED_CONTEXT_CHARS = int(os.environ.get("WORKSTREAM_CONDENSED_CONTEXT_CHARS", "1400"))


def _parse_repo_prompt_map(raw_value: str) -> Dict[str, Path]:
    """Parse repo→prompt mapping from JSON or `name=path` pairs."""
    mapping: Dict[str, Path] = {}
    if not raw_value:
        return mapping

    # Prefer JSON for clarity
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            for repo_name, prompt_path in parsed.items():
                if not isinstance(repo_name, str) or not isinstance(prompt_path, str):
                    continue
                repo_name = repo_name.strip()
                prompt_path = prompt_path.strip()
                if repo_name and prompt_path:
                    mapping[repo_name] = Path(prompt_path).expanduser()
            return mapping
    except json.JSONDecodeError:
        pass

    # Fallback: semicolon-separated "Repo=path" entries
    for chunk in raw_value.split(';'):
        if not chunk.strip() or '=' not in chunk:
            continue
        repo_name, prompt_path = chunk.split('=', 1)
        repo_name = repo_name.strip()
        prompt_path = prompt_path.strip()
        if repo_name and prompt_path:
            mapping[repo_name] = Path(prompt_path).expanduser()
    return mapping


def _parse_repo_configs(raw_value: str) -> List[Dict[str, Any]]:
    """Parse repo configurations from environment variable."""
    configs: List[Dict[str, Any]] = []
    if not raw_value:
        return configs

    # Prefer JSON array
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            for config in parsed:
                if isinstance(config, dict) and 'name' in config and 'docs_dirs' in config:
                    normalized_config = {
                        'name': str(config['name']),
                        'docs_dirs': [Path(p).expanduser() for p in config['docs_dirs'] if isinstance(p, str)]
                    }
                    repo_root = config.get('repo_root')
                    if isinstance(repo_root, str) and repo_root.strip():
                        normalized_config['repo_root'] = Path(repo_root).expanduser()
                    role = str(config.get('role', '')).strip()
                    if role:
                        normalized_config['role'] = role
                    configs.append(normalized_config)
            return configs
    except json.JSONDecodeError:
        pass

    # Fallback: semicolon-separated "name=path1,path2" entries
    for chunk in raw_value.split(';'):
        if not chunk.strip() or '=' not in chunk:
            continue
        name, paths_str = chunk.split('=', 1)
        name = name.strip()
        paths = [Path(p.strip()).expanduser() for p in paths_str.split(',') if p.strip()]
        if name and paths:
            configs.append({'name': name, 'docs_dirs': paths, 'repo_root': None})
    return configs


_DEFAULT_TRADING_SYSTEM_ROOT = r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system"


def _default_master_agent_repo_configs() -> List[Dict[str, Any]]:
    """Return the default trading-system repo prompt sources and role labels."""
    trading_system_root = Path(
        os.environ.get("TRADING_SYSTEM_ROOT_WIN", _DEFAULT_TRADING_SYSTEM_ROOT)
    )
    return [
        {
            "name": "contracts",
            "repo_root": trading_system_root / "contracts",
            "docs_dirs": [trading_system_root / "contracts" / "docs"],
            "role": "source of truth",
        },
        {
            "name": "TF",
            "repo_root": trading_system_root / "TF",
            "docs_dirs": [trading_system_root / "TF" / "docs"],
            "role": "upstream framework",
        },
        {
            "name": "Trading",
            "repo_root": trading_system_root / "Trading",
            "docs_dirs": [trading_system_root / "Trading" / "docs"],
            "role": "downstream live system",
        },
    ]


def _parse_path_list(raw_value: str) -> List[Path]:
    """Parse a list of filesystem paths from JSON array or semicolon-delimited string."""
    if not raw_value:
        return []

    # Prefer JSON array
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            return [Path(p).expanduser() for p in parsed if isinstance(p, str) and p.strip()]
    except json.JSONDecodeError:
        pass

    # Fallback: semicolon-separated paths
    return [Path(p.strip()).expanduser() for p in raw_value.split(';') if p.strip()]


def _parse_repo_root_overrides(raw_value: str) -> Dict[str, Path]:
    """Parse repo name -> repo root path overrides from JSON or `name=path` pairs."""
    mapping: Dict[str, Path] = {}
    if not raw_value:
        return mapping

    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            for repo_name, repo_path in parsed.items():
                if not isinstance(repo_name, str) or not isinstance(repo_path, str):
                    continue
                repo_name = repo_name.strip()
                repo_path = repo_path.strip()
                if repo_name and repo_path:
                    mapping[repo_name] = Path(repo_path).expanduser()
            return mapping
    except json.JSONDecodeError:
        pass

    for chunk in raw_value.split(';'):
        if not chunk.strip() or '=' not in chunk:
            continue
        repo_name, repo_path = chunk.split('=', 1)
        repo_name = repo_name.strip()
        repo_path = repo_path.strip()
        if repo_name and repo_path:
            mapping[repo_name] = Path(repo_path).expanduser()
    return mapping


def _parse_float_mapping(raw_value: str) -> Dict[str, float]:
    """Parse string/JSON mapping into lowercase float weights."""
    mapping: Dict[str, float] = {}
    if not raw_value:
        return mapping

    def _assign(key: str, value: Any) -> None:
        try:
            weight = float(value)
        except (TypeError, ValueError):
            return
        key = key.strip()
        if not key:
            return
        mapping[key.lower()] = weight

    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if isinstance(key, str):
                    _assign(key, value)
            return mapping
    except json.JSONDecodeError:
        pass

    for chunk in raw_value.split(';'):
        if '=' not in chunk:
            continue
        key, value = chunk.split('=', 1)
        _assign(key, value)
    return mapping


# Map VS Code repo names (derived from window titles) to custom prompt files.
# Edit this dict directly or set the REPO_PROMPT_MAP environment variable using
# either JSON (e.g. '{"ProjectA": "tasks/project_a_prompts.txt"}') or
# semicolon-delimited entries (e.g. 'ProjectA=tasks/project_a_prompts.txt').
DEFAULT_AGENT_SELECTION_MODE = "normal"
_raw_agent_selection_mode = os.environ.get(
    "AGENT_SELECTION_MODE",
    DEFAULT_AGENT_SELECTION_MODE,
)
AGENT_SELECTION_MODE = _raw_agent_selection_mode.strip().lower() or DEFAULT_AGENT_SELECTION_MODE

# Multi-repo configurations for master prompt orchestrator
# Set MASTER_AGENT_REPO_CONFIGS environment variable using JSON array format:
# [{"name": "repo1", "docs_dirs": ["/path/to/repo1/docs"], "role": "repo role"}, {"name": "repo2", "docs_dirs": ["/path/to/repo2/docs"], "role": "repo role"}]
# Or semicolon-delimited: "repo1=/path/to/repo1/docs;repo2=/path/to/repo2/docs"
MASTER_AGENT_REPO_CONFIGS: List[Dict[str, Any]] = _parse_repo_configs(
    os.environ.get(
        "MASTER_AGENT_REPO_CONFIGS",
        json.dumps(
            [
                {
                    "name": config["name"],
                    "repo_root": str(config["repo_root"]) if config.get("repo_root") else None,
                    "docs_dirs": [str(path) for path in config["docs_dirs"]],
                    "role": config["role"],
                }
                for config in _default_master_agent_repo_configs()
            ]
        ),
    )
)


def _discover_repo_prompt_map(feed_root: Path, repo_configs: List[Dict[str, Any]]) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    try:
        if feed_root.exists():
            for child in feed_root.iterdir():
                if child.name.startswith('.'):
                    continue
                if child.is_dir():
                    candidate = child / PROMPT_FEED_FILENAME
                    if candidate.exists():
                        mapping[child.name] = candidate
                elif child.is_file() and child.suffix.lower() in {".txt", ".md"}:
                    mapping.setdefault(child.stem, child)
    except OSError:
        pass

    for config in repo_configs:
        name = str(config.get("name", "")).strip()
        if not name:
            continue
        candidate = feed_root / name / PROMPT_FEED_FILENAME
        mapping.setdefault(name, candidate)
    return mapping


def _auto_repo_priority_weights(repo_configs: List[Dict[str, Any]]) -> Dict[str, float]:
    base = float(os.environ.get("REPO_PRIORITY_BASE_WEIGHT", "1.4"))
    step = float(os.environ.get("REPO_PRIORITY_DECREMENT", "0.1"))
    weights: Dict[str, float] = {}
    if not repo_configs:
        return weights
    for idx, config in enumerate(repo_configs):
        name = str(config.get("name", "")).strip()
        if not name:
            continue
        weight = max(DEFAULT_REPO_PRIORITY_WEIGHT, base - idx * step)
        weights[name.lower()] = round(weight, 3)
    return weights


PROMPT_FEED_FILENAME = os.environ.get("PROMPT_FEED_FILENAME", FINISHED_PANEL_PROMPT_PATH.name or "latest.txt")
PROMPT_FEED_ROOT = FINISHED_PANEL_PROMPT_PATH.parent
DEFAULT_REPO_PRIORITY_WEIGHT = float(os.environ.get("DEFAULT_REPO_PRIORITY_WEIGHT", "1.0"))

REPO_PROMPT_MAP: Dict[str, Path] = _discover_repo_prompt_map(PROMPT_FEED_ROOT, MASTER_AGENT_REPO_CONFIGS)
REPO_PROMPT_MAP.update(_parse_repo_prompt_map(os.environ.get("REPO_PROMPT_MAP", "")))

REPO_PRIORITY_WEIGHTS: Dict[str, float] = _auto_repo_priority_weights(MASTER_AGENT_REPO_CONFIGS)
REPO_PRIORITY_WEIGHTS.update(_parse_float_mapping(os.environ.get("REPO_PRIORITY_WEIGHTS", "")))

MODEL_PRIORITY_WEIGHTS: Dict[str, float] = {
    "gpt-5.1-codex-max (preview)": float(os.environ.get("MODEL_PRIORITY_WEIGHT_CODEX_MAX", "1.25")),
    "gpt-5.1 codex": float(os.environ.get("MODEL_PRIORITY_WEIGHT_CODEX", "1.15")),
    "gpt-5.1 codex mini": float(os.environ.get("MODEL_PRIORITY_WEIGHT_CODEX_MINI", "1.05")),
    "grok": float(os.environ.get("MODEL_PRIORITY_WEIGHT_GROK", "0.9")),
}
MODEL_PRIORITY_WEIGHTS.update(_parse_float_mapping(os.environ.get("MODEL_PRIORITY_WEIGHTS", "")))


# ============================================================================
# CROSS-REPO TODO INGESTION (MASTER PROMPT ORCHESTRATOR SUPPORT)
# ============================================================================

# Enable cross-repo Todo discovery + parsing into a structured cache.
CROSS_REPO_TODO_ENABLED = os.environ.get("CROSS_REPO_TODO_ENABLED", "true").lower() == "true"

# Refresh cadence for re-scanning sibling repositories (0 disables auto-refresh).
CROSS_REPO_TODO_REFRESH_INTERVAL_SECONDS = int(
    os.environ.get("CROSS_REPO_TODO_REFRESH_INTERVAL_SECONDS", "300")
)

# Where to persist the parsed snapshot (JSON).
CROSS_REPO_TODO_CACHE_PATH = Path(
    os.environ.get("CROSS_REPO_TODO_CACHE_PATH", "automation/cross_repo_todo_cache.json")
).expanduser()

# Extra search roots (directories containing sibling repos), beyond workspace_root.parent.
# Format: JSON array of paths OR semicolon-separated list.
CROSS_REPO_TODO_SEARCH_ROOTS: List[Path] = _parse_path_list(
    os.environ.get("CROSS_REPO_TODO_SEARCH_ROOTS", "")
)

# Explicit repo root overrides (name -> path). If provided, these repos are always scanned.
# Format: JSON object OR semicolon-separated name=path entries.
CROSS_REPO_TODO_REPO_OVERRIDES: Dict[str, Path] = _parse_repo_root_overrides(
    os.environ.get("CROSS_REPO_TODO_REPO_OVERRIDES", "")
)

# Auto-populate the three trading-system repos when no explicit overrides are set.
# This ensures the cross-repo TODO scanner always discovers Trading, TF, and contracts
# without requiring manual env var configuration.
if not CROSS_REPO_TODO_REPO_OVERRIDES and not os.environ.get("CROSS_REPO_TODO_REPO_OVERRIDES"):
    _ts_root_for_todo = Path(
        os.environ.get(
            "TRADING_SYSTEM_ROOT_WIN",
            r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system",
        )
    )
    CROSS_REPO_TODO_REPO_OVERRIDES = {
        "Trading": _ts_root_for_todo / "Trading",
        "TF": _ts_root_for_todo / "TF",
        "contracts": _ts_root_for_todo / "contracts",
        "trading-system": _ts_root_for_todo,
        "desktop-agent-automation": Path(__file__).parent.parent,
    }


# ============================================================================
# TASK DISCOVERY DAEMON CONFIGURATION
# ============================================================================

# How often to audit for low task feeds (seconds).
TASK_DISCOVERY_INTERVAL_SECONDS = int(
    os.environ.get("TASK_DISCOVERY_INTERVAL_SECONDS", "900")
)

# Minimum remaining tasks before triggering a new audit.
TASK_DISCOVERY_LOW_TASK_THRESHOLD = int(
    os.environ.get("TASK_DISCOVERY_LOW_TASK_THRESHOLD", "2")
)

# Autostart task discovery daemon even without --autonomous.
TASK_DISCOVERY_AUTOSTART = os.environ.get("TASK_DISCOVERY_AUTOSTART", "true").lower() == "true"

# Background Copilot usage monitor settings.
ENABLE_COPILOT_USAGE_MONITOR = os.environ.get("ENABLE_COPILOT_USAGE_MONITOR", "true").lower() == "true"
COPILOT_USAGE_MONITOR_INTERVAL_SECONDS = float(
    os.environ.get("COPILOT_USAGE_MONITOR_INTERVAL_SECONDS", "300")
)

# Model picker labels as seen in the UI
MODEL_PICKER_LABELS = {
    "grok": "Grok",
    "codex-mini": "GPT-5.1 Codex Mini",
    "codex": "GPT-5.1 Codex",
    "codex-max": "GPT-5.1-Codex-Max (Preview)",
}


# ============================================================================
# AUTO-PAUSE ON TYPING CONFIGURATION
# ============================================================================

# Disabled by default - was triggering false positives
AUTO_PAUSE_ON_TYPING = False

# Resume after this many seconds of no typing
TYPING_IDLE_SECONDS = 5.0

# Auto-pause automation if any keyboard key is pressed (immediate manual pause).
# This is a safety feature to regain control quickly.
AUTO_PAUSE_ON_KEYBOARD_INPUT = os.environ.get("AUTO_PAUSE_ON_KEYBOARD_INPUT", "true").lower() == "true"

# Auto-pause automation when the physical mouse moves a lot
AUTO_PAUSE_ON_MOUSE_MOVE = os.environ.get("AUTO_PAUSE_ON_MOUSE_MOVE", "true").lower() == "true"

# Pixels - ignore mouse jiggles smaller than this
MOUSE_MOVEMENT_THRESHOLD = int(os.environ.get("MOUSE_MOVEMENT_THRESHOLD", "120"))

# Auto-pause automation if the cursor drifts away from where automation last set it
# Useful when automation is running across desktops and you need it to stop immediately.
AUTO_PAUSE_ON_CURSOR_DRIFT = os.environ.get("AUTO_PAUSE_ON_CURSOR_DRIFT", "true").lower() == "true"

# Pixels - if cursor is farther than this from the last automation cursor position, pause.
CURSOR_DRIFT_THRESHOLD_PX = int(os.environ.get("CURSOR_DRIFT_THRESHOLD_PX", "100"))

# Pixels - while paused for drift, require this much motion before extending the pause window
CURSOR_DRIFT_STABILITY_PX = float(os.environ.get("CURSOR_DRIFT_STABILITY_PX", "50"))

# Persist cursor checkpoints to logs (jsonl)
CURSOR_GUARD_LOG = os.environ.get("CURSOR_GUARD_LOG", "true").lower() == "true"

# Seconds to pause after significant mouse movement
MOUSE_PAUSE_SECONDS = int(os.environ.get("MOUSE_PAUSE_SECONDS", "20"))

# Speak pause/resume events aloud
SPEAK_PAUSE_EVENTS = True


# ============================================================================
# HOTKEY CONFIGURATION
# ============================================================================

# Hotkey to toggle pause/resume
PAUSE_HOTKEY = 'ctrl+shift+p'

# Hotkey to wait extra time
EXTRA_WAIT_HOTKEY = 'ctrl+shift+w'


def parse_hotkey_to_vk(hotkey_str: str) -> Tuple[int, int]:
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


# Pre-parsed hotkeys for performance
PARSED_PAUSE_HOTKEY = parse_hotkey_to_vk(PAUSE_HOTKEY)
PARSED_EXTRA_WAIT_HOTKEY = parse_hotkey_to_vk(EXTRA_WAIT_HOTKEY)


# ============================================================================
# WINDOW PRIORITY PATTERNS
# ============================================================================

# Windows containing these patterns (case-insensitive) are processed first
WINDOW_PRIORITY_PATTERNS = [
    "tf",           # TF desktop/project windows - highest priority
    "trading",      # Trading desktop/project windows - second priority
]

# VS Code window title suffix
VSCODE_TITLE_SUFFIX = " - Visual Studio Code"


# ============================================================================
# LOG VERBOSITY
# ============================================================================

# "normal" = standard output, "quiet" = only important events, "verbose" = all details
LOG_VERBOSITY = os.environ.get("LOG_VERBOSITY", "normal").lower()


# ============================================================================
# MASTER AGENT CONFIGURATION
# ============================================================================

ENABLE_MASTER_AGENT = True
NO_ALLOW_TRIGGER_MINUTES = int(os.environ.get("NO_ALLOW_TRIGGER_MINUTES", "20"))
PROMPT_GENERATION_COOLDOWN_MINUTES = int(os.environ.get("PROMPT_GENERATION_COOLDOWN_MINUTES", "90"))
MASTER_AGENT_MODEL = os.environ.get("MASTER_AGENT_MODEL", OPENAI_COORDINATION_MODEL)
MASTER_AGENT_MAX_DOCS = int(os.environ.get("MASTER_AGENT_MAX_DOCS", "18"))
MASTER_AGENT_MAX_CHARS = int(os.environ.get("MASTER_AGENT_MAX_CHARS", "3500"))


# ============================================================================
# PATH CONFIGURATION
# ============================================================================

# Root of the trading-system monorepo on WSL (shared by TF, contracts, Trading)
# Override via env var for non-standard installations.
TRADING_SYSTEM_ROOT: Path = Path(
    os.environ.get("TRADING_SYSTEM_ROOT_WIN", _DEFAULT_TRADING_SYSTEM_ROOT)
)

# Per-repo roots within TRADING_SYSTEM_ROOT
TRADING_REPO_ROOT: Path = Path(os.environ.get("TRADING_REPO_ROOT", str(TRADING_SYSTEM_ROOT / "Trading")))
TF_REPO_ROOT: Path = Path(os.environ.get("TF_REPO_ROOT", str(TRADING_SYSTEM_ROOT / "TF")))
CONTRACTS_REPO_ROOT: Path = Path(os.environ.get("CONTRACTS_REPO_ROOT", str(TRADING_SYSTEM_ROOT / "contracts")))

# ============================================================================
# NORTH STAR / COORDINATION CONFIGURATION
# ============================================================================

# Enable the North Star context injection into generated prompts.
# When enabled, every prompt is prefixed with the primary goal and active in-flight tasks.
NORTH_STAR_ENABLED: bool = os.environ.get("NORTH_STAR_ENABLED", "true").lower() == "true"

# Enable the CoordinationGuard pre-dispatch check.
# Detects overlaps, drift, and boundary violations before a prompt is sent.
COORDINATION_GUARD_ENABLED: bool = os.environ.get("COORDINATION_GUARD_ENABLED", "true").lower() == "true"

# Block dispatch when CoordinationGuard detects an in-progress overlap.
# Default False = warn only; set True to hard-block.
COORDINATION_GUARD_BLOCK_OVERLAPS: bool = (
    os.environ.get("COORDINATION_GUARD_BLOCK_OVERLAPS", "false").lower() == "true"
)

# How many seconds to cache the North Star / LedgerReport before refreshing.
NORTH_STAR_CACHE_TTL_SECONDS: int = int(os.environ.get("NORTH_STAR_CACHE_TTL_SECONDS", "300"))
WSL_PATH_PROBE_TIMEOUT_SECONDS = float(os.environ.get("WSL_PATH_PROBE_TIMEOUT_SECONDS", "3.0"))
ENABLE_WSL_DOC_CACHE = os.environ.get("ENABLE_WSL_DOC_CACHE", "true").lower() == "true"

# ============================================================================
# MASTER AGENT PATH CONFIGURATION
# ============================================================================

WSL_DOCS_ROOT = Path(
    os.environ.get(
        "MASTER_AGENT_DOCS_ROOT",
        str(TRADING_SYSTEM_ROOT / "Trading" / "docs"),
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


# ============================================================================
# BUTTON NAME CONSTANTS
# ============================================================================

# Allow button names (full and short versions)
ALLOW_BUTTON_NAMES = [
    "Allow (Ctrl+Enter)",
    "Allow",
]

# Keep edits button names
KEEP_BUTTON_NAMES = [
    "Keep All Edits (Ctrl+Enter)",
    "Keep this Change (Ctrl+Y)",
    "Keep Chat Edits in this File (Ctrl+Shift+Y)",
    "Keep",
]

# All action buttons we want to click
ALL_ACTION_BUTTON_NAMES = ALLOW_BUTTON_NAMES + KEEP_BUTTON_NAMES + ["Try Again"]


# ============================================================================
# NO-CLICK ALERT CONFIGURATION
# ============================================================================

# Speak a warning if no action clicks occur within this many minutes of active scanning
ENABLE_NO_CLICK_ALERT = os.environ.get("ENABLE_NO_CLICK_ALERT", "true").lower() == "true"
NO_CLICK_ALERT_MINUTES = int(os.environ.get("NO_CLICK_ALERT_MINUTES", "15"))


# ============================================================================
# DATACLASS FOR RUNTIME CONFIG (optional future use)
# ============================================================================

@dataclass
class RuntimeConfig:
    """
    Runtime configuration that can be modified during execution.
    
    This is for values that may change based on user interaction
    or runtime conditions.
    """
    is_paused: bool = False
    is_auto_paused: bool = False
    current_desktop: int = 1
    desktop_sync_done: bool = False
    
    # Timing overrides
    extra_wait_until: float = 0.0  # datetime.min as timestamp
    next_allowed_check: float = 0.0
    
    # Grace period tracking
    grace_period_end: float = 0.0
    pre_cooldown_fingerprints: set = field(default_factory=set)
