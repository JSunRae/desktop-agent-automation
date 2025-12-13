from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pyautogui
import keyboard

from automation.ui.window_utils import set_cursor_pos, send_mouse_click

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
DEFAULT_TASK_FILE = BASE_DIR.parent / "tasks" / "example_tasks.txt"

Coordinates = Tuple[int, int]
ConfigEntry = Optional[Coordinates]
ConfigData = Dict[str, ConfigEntry]
ButtonMap = Dict[str, Coordinates]
StateData = Dict[str, int]

BUTTON_COUNT = 8
BUTTON_KEYS = [f"button_{idx + 1}" for idx in range(BUTTON_COUNT)]


# File helpers


def _write_json(path: Path, payload: Dict) -> None:
    """Write a JSON payload to the specified file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _read_json(path: Path, default: Dict) -> Dict:
    """Read JSON from disk or return the provided default value."""
    if not path.exists():
        _write_json(path, default)
        return default.copy()
    with path.open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return default.copy()


# Configuration helpers


def load_config() -> ConfigData:
    """Load automation configuration from disk with fallback defaults."""
    defaults = {"copilot_input": None, "copilot_button": None}
    defaults.update({key: None for key in BUTTON_KEYS})
    raw = _read_json(CONFIG_PATH, defaults)
    return {
        key: tuple(value) if isinstance(value, (list, tuple)) and len(value) == 2 else None
        for key, value in raw.items()
    }


def save_config(config: ConfigData) -> None:
    """Serialize and persist the automation configuration."""
    payload = {
        key: list(value) if isinstance(value, tuple) else None
        for key, value in config.items()
    }
    _write_json(CONFIG_PATH, payload)


def capture_position(prompt: str) -> Coordinates:
    """Capture a screen coordinate when the user presses F9."""
    print(prompt)
    print("Press F9 to capture the position.")
    keyboard.wait("f9")
    time.sleep(0.1)
    position = pyautogui.position()
    print(f"Captured position at {position.x}, {position.y}")
    return position.x, position.y


def configure_positions() -> ConfigData:
    """Interactively capture Copilot hotspots and button sequence coordinates."""
    print("== Desktop automation configuration ==")
    print("Position VS Code so Copilot is visible and ready before continuing.")
    config = load_config()
    config["copilot_input"] = capture_position("Hover over the Copilot input field.")
    config["copilot_button"] = capture_position(
        "Hover over the blue Continue/Run/Apply button."
    )
    for key in BUTTON_KEYS:
        config[key] = capture_position(f"Hover over button {key} and press F9.")
    save_config(config)
    print("Configuration saved to config.json.")
    return config


def load_button_map(config: ConfigData) -> ButtonMap:
    """Return only the stored button coordinates."""
    result: ButtonMap = {}
    for key in BUTTON_KEYS:
        coords = config.get(key)
        if coords is not None:
            result[key] = coords
    return result


def configure_cycle(config: ConfigData, interval: float) -> None:
    """Click through the stored button map every `interval` seconds."""
    button_map = load_button_map(config)
    if not button_map:
        print("No custom button positions have been recorded. Run --config first.")
        return
    print(f"Starting button cycle every {interval} seconds on {len(button_map)} keys.")
    try:
        while True:
            start = time.time()
            for name, coords in button_map.items():
                print(f"Clicking {name} at {coords}")
                set_cursor_pos(coords[0], coords[1])
                send_mouse_click()
                time.sleep(0.1)
            elapsed = time.time() - start
            sleep_duration = max(0, interval - elapsed)
            if sleep_duration:
                time.sleep(sleep_duration)
    except KeyboardInterrupt:
        print("Button cycling interrupted.")


def validate_config(config: ConfigData) -> bool:
    """Return True if the Copilot coordinates exist."""
    return bool(config.get("copilot_input") and config.get("copilot_button"))


# Task helpers


def load_tasks(task_file: Path) -> List[str]:
    """Load a list of cleaned tasks from the provided text file."""
    if not task_file.exists():
        raise FileNotFoundError(f"Task file not found: {task_file}")
    with task_file.open("r", encoding="utf-8") as handle:
        tasks = [line.strip() for line in handle if line.strip()]
    return tasks


def load_state() -> StateData:
    """Load the persisted task progress state."""
    return _read_json(STATE_PATH, {"current_task": 0})


def save_state(state: StateData) -> None:
    """Persist the updated task progress state."""
    _write_json(STATE_PATH, state)


def get_next_task(tasks: List[str], state: StateData) -> Optional[str]:
    """Return the next task or None if the list has been exhausted."""
    current_index = state.get("current_task", 0)
    if current_index >= len(tasks):
        return None
    return tasks[current_index]


def advance_state(state: StateData) -> None:
    """Increment the current task index and persist the state."""
    state["current_task"] = state.get("current_task", 0) + 1
    save_state(state)


# Automation helpers


def send_task(task: str, config: ConfigData) -> None:
    """Use pyautogui to write the task into the Copilot input box."""
    coords = config.get("copilot_input")
    if coords is None:
        print("Copilot input coordinates are missing. Run with --config to capture them.")
        return
    print(f"Sending task: {task}")
    set_cursor_pos(coords[0], coords[1])
    send_mouse_click()
    time.sleep(0.3)
    pyautogui.write(task, interval=0.02)
    pyautogui.press("enter")


def click_copilot_button(config: ConfigData) -> None:
    """Click the Copilot approval button using the stored coordinates."""
    coords = config.get("copilot_button")
    if coords is None:
        print("Copilot button coordinates are missing. Run with --config to capture them.")
        return
    set_cursor_pos(coords[0], coords[1])
    send_mouse_click()


def print_status(tasks: List[str], state: StateData, config: ConfigData) -> None:
    """Print the current automation status to the console."""
    total = len(tasks)
    current = state.get("current_task", 0)
    next_task = tasks[current] if current < total else "<none>"
    print("== Copilot automation status ==")
    print(f"Current index: {current} / {total}")
    print(f"Next task: {next_task}")
    print(f"Input coordinate: {config.get('copilot_input')}")
    print(f"Button coordinate: {config.get('copilot_button')}")


def bind_hotkeys(tasks: List[str], state: StateData, config: ConfigData) -> None:
    """Register global hotkeys for automation actions."""

    def _send_next() -> None:
        task = get_next_task(tasks, state)
        if task is None:
            print("All tasks have been sent. Reset the state file to start over.")
            return
        send_task(task, config)
        advance_state(state)

    keyboard.add_hotkey("ctrl+alt+n", _send_next)
    keyboard.add_hotkey("ctrl+alt+c", lambda: click_copilot_button(config))
    keyboard.add_hotkey("ctrl+alt+s", lambda: print_status(tasks, state, config))


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Desktop automation for Copilot tasks and button cycling."
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Run interactive coordinate configuration and exit.",
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=DEFAULT_TASK_FILE,
        help="Path to the task file to process.",
    )
    parser.add_argument(
        "--click-loop",
        action="store_true",
        help="Run the periodic button click loop instead of hotkeys.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Interval in seconds between button cycles (default: 60).",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the desktop automation toolkit."""
    args = parse_arguments()
    if args.config:
        configure_positions()
        return

    config = load_config()
    if not validate_config(config):
        print("Missing Copilot coordinates. Run with --config to set them.")
        sys.exit(1)

    if args.click_loop:
        configure_cycle(config, args.interval)
        return

    try:
        tasks = load_tasks(args.tasks)
    except FileNotFoundError as exc:
        print(str(exc))
        sys.exit(1)

    state = load_state()
    bind_hotkeys(tasks, state, config)

    print("Hotkeys registered:")
    print("  Ctrl+Alt+N -> send next task")
    print("  Ctrl+Alt+C -> click Copilot button")
    print("  Ctrl+Alt+S -> print status")
    print("  Esc -> exit")
    print("Press Esc when you are done.")

    keyboard.wait("esc")
    print("Exiting Copilot automation.")


if __name__ == "__main__":
    main()
