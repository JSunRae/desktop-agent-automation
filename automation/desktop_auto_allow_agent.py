"""
Desktop Auto-Allow Agent using OpenAI Computer Use API.

This module implements an agent that:
- Takes screenshots every 1 minute
- Calls OpenAI's computer-use-preview model
- Detects and clicks GitHub Copilot Agent approval buttons
- Handles rate limiting with 20-minute cooldowns
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import pyautogui
from openai import OpenAI
from PIL import Image, ImageGrab

from automation.utils import ensure_log_file, log_message
from automation.cost_tracker import get_cost_tracker

_COST_TRACKER = get_cost_tracker()

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "auto_allow_config.json"
LOG_PATH = BASE_DIR / "auto_allow.log"

Status = Literal["CLICKED", "NO_BUTTON", "RATE_LIMITED"]

# System prompt for the OpenAI Computer Use agent
SYSTEM_PROMPT = """You are operating on a Windows desktop with Visual Studio Code open.

**Your ONLY task**: Look for GitHub Copilot Agent approval buttons and click them if safe.

**Valid approval buttons** are inside VS Code's Copilot UI and have text like:
- "Allow", "Continue", "Run anyway", "Apply changes", "Approve", "Proceed"
- Usually blue or high-contrast rectangular buttons
- Part of the Copilot Agent or Copilot chat interface

**Your response must end with ONE of these status lines:**
- `STATUS: CLICKED` - If you clicked an approval button
- `STATUS: RATE_LIMITED` - If you see rate limit messages like "You've reached the limit" or "Too many requests"
- `STATUS: NO_BUTTON` - If no approval button is visible or you're uncertain

**Safety rules (CRITICAL):**
- NEVER click window controls (close, minimize, maximize)
- NEVER click taskbar, Start menu, or system tray
- NEVER type text or use keyboard shortcuts
- NEVER interact with terminals, file explorers, or browsers
- ONLY click Copilot approval buttons in VS Code
- If uncertain, return `STATUS: NO_BUTTON`
- Maximum ONE click per invocation

Be conservative. When in doubt, do nothing."""


class AutoAllowAgent:
    """Desktop Auto-Allow Agent using OpenAI Computer Use API."""

    def __init__(
        self, 
        api_key: Optional[str] = None, 
        dry_run: bool = False,
        monitor_indices: Optional[List[int]] = None,
        quadrant: Optional[str] = None
    ):
        """
        Initialize the agent.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            dry_run: If True, don't actually click - just log what would happen
            monitor_indices: List of monitor indices to capture (0-based). None = all monitors
            quadrant: Quadrant to capture: "bottom-left", "bottom-right", "top-left", "top-right", or None
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.dry_run = dry_run
        self.rate_limit_until: Optional[datetime] = None
        self.monitor_indices = monitor_indices
        self.quadrant = quadrant
        
        # Store region offsets for coordinate mapping
        self.last_capture_regions: List[Tuple[int, int, int, int]] = []
        self.last_capture_quadrant: Optional[str] = None

        ensure_log_file(LOG_PATH)

    def get_monitor_regions(self) -> List[Tuple[int, int, int, int]]:
        """
        Get bounding boxes for all monitors.
        
        Returns:
            List of (left, top, right, bottom) tuples for each monitor
        """
        try:
            from screeninfo import get_monitors
            monitors = get_monitors()
            return [(m.x, m.y, m.x + m.width, m.y + m.height) for m in monitors]
        except ImportError:
            # Fallback: return full screen
            log_message("screeninfo not available, using full screen", LOG_PATH)
            full_screen = ImageGrab.grab()
            return [(0, 0, full_screen.width, full_screen.height)]

    def capture_screenshot(
        self, 
        regions: Optional[List[Tuple[int, int, int, int]]] = None,
        quadrant: Optional[str] = None
    ) -> str:
        """
        Capture screenshot of specified regions or full desktop.

        Args:
            regions: List of (left, top, right, bottom) bounding boxes to capture.
                    If None, captures full desktop.
            quadrant: Which quadrant to capture from each region:
                     "bottom-left", "bottom-right", "top-left", "top-right", or None for full

        Returns:
            Base64-encoded PNG image
        """
        import traceback
        import sys
        
        # Store for coordinate mapping later
        self.last_capture_regions = regions or []
        self.last_capture_quadrant = quadrant
        
        try:
            if regions is None:
                # Full desktop capture
                screenshot = ImageGrab.grab()
            else:
                # Capture multiple regions and stitch them
                screenshots = []
                for bbox in regions:
                    region_img = ImageGrab.grab(bbox=bbox)
                    
                    # Crop to quadrant if specified
                    if quadrant:
                        region_img = self._crop_to_quadrant(region_img, quadrant)
                    
                    screenshots.append(region_img)
                
                # Stitch screenshots vertically
                if len(screenshots) == 1:
                    screenshot = screenshots[0]
                else:
                    total_height = sum(img.height for img in screenshots)
                    max_width = max(img.width for img in screenshots)
                    screenshot = Image.new('RGB', (max_width, total_height))
                    y_offset = 0
                    for img in screenshots:
                        screenshot.paste(img, (0, y_offset))
                        y_offset += img.height

            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode("utf-8")
        except Exception as e:
            error_msg = f"Failed to capture screenshot: {e}"
            log_message(error_msg, LOG_PATH)
            print(f"Error: {error_msg}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            raise RuntimeError(f"Screenshot capture failed: {e}") from e
    
    def _crop_to_quadrant(self, img: Image.Image, quadrant: str) -> Image.Image:
        """
        Crop image to specified quadrant or half.
        
        Args:
            img: PIL Image to crop
            quadrant: "bottom-left", "bottom-right", "top-left", "top-right",
                     "right-half", "left-half", "top-half", "bottom-half"
            
        Returns:
            Cropped PIL Image
        """
        width, height = img.size
        mid_x, mid_y = width // 2, height // 2
        
        # Standard quadrants
        if quadrant == "bottom-left":
            return img.crop((0, mid_y, mid_x, height))
        elif quadrant == "bottom-right":
            return img.crop((mid_x, mid_y, width, height))
        elif quadrant == "top-left":
            return img.crop((0, 0, mid_x, mid_y))
        elif quadrant == "top-right":
            return img.crop((mid_x, 0, width, mid_y))
        
        # Half regions (better coverage)
        elif quadrant == "right-half":
            return img.crop((mid_x, 0, width, height))
        elif quadrant == "left-half":
            return img.crop((0, 0, mid_x, height))
        elif quadrant == "top-half":
            return img.crop((0, 0, width, mid_y))
        elif quadrant == "bottom-half":
            return img.crop((0, mid_y, width, height))
        
        else:
            return img

    def call_openai_computer_use(self, screenshot_b64: str) -> Tuple[Status, Optional[Dict]]:
        """
        Call OpenAI API with a screenshot to detect approval buttons.
        Falls back to GPT-4 Vision if computer-use-preview is not available.

        Args:
            screenshot_b64: Base64-encoded screenshot image

        Returns:
            Tuple of (status, click_action)
            - status: One of "CLICKED", "NO_BUTTON", "RATE_LIMITED"
            - click_action: Dict with x, y coordinates if a click was requested, else None
        """
        try:
            # Get screen dimensions
            try:
                screenshot_pil = ImageGrab.grab()
                display_width, display_height = screenshot_pil.size
            except Exception as e:
                log_message(f"Failed to get screen dimensions: {e}", LOG_PATH)
                # Fallback to common resolution
                display_width, display_height = 1920, 1080
            
            # Try computer-use-preview first (if available)
            try:
                response = self.client.responses.create(
                    model="computer-use-preview",
                    tools=[{
                        "type": "computer_use_preview",
                        "display_width": display_width,
                        "display_height": display_height,
                        "environment": "windows"
                    }],
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": f"{SYSTEM_PROMPT}\n\nCheck if there is a GitHub Copilot Agent approval button to click."
                                },
                                {
                                    "type": "input_image",
                                    "image_url": f"data:image/png;base64,{screenshot_b64}"
                                }
                            ]
                        }
                    ],
                    reasoning={
                        "summary": "concise"
                    },
                    truncation="auto"
                )
            except Exception as e:
                if "model_not_found" in str(e) or "computer-use-preview" in str(e):
                    log_message("computer-use-preview not available, falling back to GPT-4 Vision", LOG_PATH)
                    return self._call_gpt4_vision_fallback(screenshot_b64, display_width, display_height)
                log_message(f"OpenAI API error: {e}", LOG_PATH)
                raise

            # Process the response output
            status: Status = "NO_BUTTON"
            click_action: Optional[Dict] = None
            
            for item in response.output:
                # Check for computer_call items
                if hasattr(item, 'type') and item.type == "computer_call":
                    action = item.action
                    if action.type == "click":
                        click_action = {
                            "x": action.x,
                            "y": action.y
                        }
                        status = "CLICKED"
                        log_message(f"Model requested click at ({action.x}, {action.y})", LOG_PATH)
                
                # Check for text responses with status indicators
                elif hasattr(item, 'type') and item.type == "text":
                    text_content = getattr(item, 'text', '')
                    if "STATUS: RATE_LIMITED" in text_content:
                        status = "RATE_LIMITED"
                    elif "STATUS: NO_BUTTON" in text_content:
                        status = "NO_BUTTON"
                    log_message(f"Model response: {text_content[:200]}", LOG_PATH)

            usage = getattr(response, "usage", None)
            _COST_TRACKER.record_vision_usage(
                source="desktop_auto_allow",
                event="computer_use_preview",
                model="computer-use-preview",
                usage=usage,
                image_count=1,
                details={"status": status},
            )
            return status, click_action

        except Exception as e:
            log_message(f"Error calling OpenAI API: {e}", LOG_PATH)
            return "NO_BUTTON", None

    def _call_gpt4_vision_fallback(self, screenshot_b64: str, display_width: int, display_height: int) -> Tuple[Status, Optional[Dict]]:
        """
        Fallback to GPT-4 Vision when computer-use-preview is not available.
        Uses text-based response parsing instead of structured computer_call.

        Args:
            screenshot_b64: Base64-encoded screenshot
            display_width: Screen width
            display_height: Screen height

        Returns:
            Tuple of (status, click_action)
        """
        try:
            prompt = f"""{SYSTEM_PROMPT}

IMPORTANT: Since computer-use tool is not available, respond with:
1. Your status line (STATUS: CLICKED, STATUS: NO_BUTTON, or STATUS: RATE_LIMITED)
2. If STATUS: CLICKED, provide coordinates in format: CLICK_AT: x=<number>, y=<number>

Screen dimensions: {display_width}x{display_height}

Check if there is a GitHub Copilot Agent approval button to click."""

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=300
            )

            response_text = response.choices[0].message.content or ""
            log_message(f"GPT-4 Vision response: {response_text[:200]}", LOG_PATH)

            # Parse status
            status: Status = "NO_BUTTON"
            click_action: Optional[Dict] = None

            if "STATUS: CLICKED" in response_text:
                status = "CLICKED"
                # Parse coordinates from response
                import re
                coord_match = re.search(r'CLICK_AT:\s*x=(\d+),\s*y=(\d+)', response_text)
                if coord_match:
                    click_action = {
                        "x": int(coord_match.group(1)),
                        "y": int(coord_match.group(2))
                    }
                    log_message(f"Parsed click coordinates: ({click_action['x']}, {click_action['y']})", LOG_PATH)
                else:
                    log_message("Warning: CLICKED status but no coordinates found", LOG_PATH)
                    status = "NO_BUTTON"
            elif "STATUS: RATE_LIMITED" in response_text:
                status = "RATE_LIMITED"
            elif "STATUS: NO_BUTTON" in response_text:
                status = "NO_BUTTON"

            usage = getattr(response, "usage", None)
            _COST_TRACKER.record_vision_usage(
                source="desktop_auto_allow",
                event="gpt4_vision_fallback",
                model="gpt-4o",
                usage=usage,
                image_count=1,
                details={"status": status},
            )

            return status, click_action

        except Exception as e:
            log_message(f"Error in GPT-4 Vision fallback: {e}", LOG_PATH)
            return "NO_BUTTON", None

    def _map_screenshot_to_desktop_coords(self, x: int, y: int) -> Tuple[int, int]:
        """
        Map coordinates from screenshot space to desktop space.
        
        Args:
            x, y: Coordinates in the screenshot
            
        Returns:
            (x, y) coordinates in desktop space
        """
        if not self.last_capture_regions:
            # Full desktop capture, no mapping needed
            return (x, y)
        
        # Determine which region the click is in (for stitched screenshots)
        y_offset = 0
        for region in self.last_capture_regions:
            left, top, right, bottom = region
            region_width = right - left
            region_height = bottom - top
            
            # Calculate cropped dimensions based on region type
            cropped_width = region_width
            cropped_height = region_height
            x_offset_in_region = 0
            y_offset_in_region = 0
            
            if self.last_capture_quadrant:
                # Standard quadrants (1/4 size)
                if self.last_capture_quadrant in ["bottom-left", "bottom-right", "top-left", "top-right"]:
                    cropped_width = region_width // 2
                    cropped_height = region_height // 2
                    
                    if "right" in self.last_capture_quadrant:
                        x_offset_in_region = region_width // 2
                    if "bottom" in self.last_capture_quadrant:
                        y_offset_in_region = region_height // 2
                
                # Half regions (1/2 size)
                elif self.last_capture_quadrant == "right-half":
                    cropped_width = region_width // 2
                    x_offset_in_region = region_width // 2
                elif self.last_capture_quadrant == "left-half":
                    cropped_width = region_width // 2
                elif self.last_capture_quadrant == "top-half":
                    cropped_height = region_height // 2
                elif self.last_capture_quadrant == "bottom-half":
                    cropped_height = region_height // 2
                    y_offset_in_region = region_height // 2
            
            # Check if click is in this region
            if y < y_offset + cropped_height:
                # Map x, y back to this region
                region_x = x
                region_y = y - y_offset
                
                # Apply offsets to get desktop coordinates
                desktop_x = left + x_offset_in_region + region_x
                desktop_y = top + y_offset_in_region + region_y
                
                return (desktop_x, desktop_y)
            
            y_offset += cropped_height
        
        # Fallback: use coordinates as-is
        return (x, y)

    def execute_click(self, x: int, y: int) -> None:
        """
        Execute a mouse click at the specified coordinates.

        Args:
            x: X coordinate in screenshot space
            y: Y coordinate in screenshot space
        """
        import traceback
        import sys
        
        try:
            # Map screenshot coordinates to desktop coordinates
            desktop_x, desktop_y = self._map_screenshot_to_desktop_coords(x, y)
            
            if self.dry_run:
                log_message(f"[DRY RUN] Would click at screenshot ({x}, {y}) -> desktop ({desktop_x}, {desktop_y})", LOG_PATH)
                return

            log_message(f"Clicking at screenshot ({x}, {y}) -> desktop ({desktop_x}, {desktop_y})", LOG_PATH)
            from automation.ui.window_utils import set_cursor_pos, send_mouse_click

            set_cursor_pos(desktop_x, desktop_y)
            send_mouse_click()
        except Exception as e:
            error_msg = f"Failed to execute click at ({x}, {y}): {e}"
            log_message(error_msg, LOG_PATH)
            print(f"Error: {error_msg}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            raise RuntimeError(f"Click execution failed: {e}") from e

    def check_and_click(self) -> Status:
        """
        Main method: capture screenshot, call OpenAI, and execute action if needed.

        Returns:
            Status indicating what happened
        """
        import traceback
        import sys
        
        try:
            # Check if we're in rate limit cooldown
            if self.rate_limit_until and datetime.now() < self.rate_limit_until:
                remaining = (self.rate_limit_until - datetime.now()).total_seconds()
                log_message(f"In rate limit cooldown. {remaining:.0f} seconds remaining.", LOG_PATH)
                return "RATE_LIMITED"

            # Determine which regions to capture
            regions = None
            if self.monitor_indices is not None:
                all_regions = self.get_monitor_regions()
                regions = [all_regions[i] for i in self.monitor_indices if i < len(all_regions)]
                log_message(f"Capturing {len(regions)} monitor region(s), quadrant: {self.quadrant or 'full'}", LOG_PATH)
            else:
                log_message("Capturing full desktop...", LOG_PATH)

            screenshot_b64 = self.capture_screenshot(regions=regions, quadrant=self.quadrant)

            log_message("Calling OpenAI Computer Use API...", LOG_PATH)
            status, click_action = self.call_openai_computer_use(screenshot_b64)

            if status == "CLICKED" and click_action:
                self.execute_click(click_action["x"], click_action["y"])
            elif status == "RATE_LIMITED":
                self.rate_limit_until = datetime.now() + timedelta(minutes=20)
                log_message(f"Rate limit detected. Cooldown until {self.rate_limit_until}", LOG_PATH)
            elif status == "NO_BUTTON":
                log_message("No approval button detected.", LOG_PATH)

            return status
        except Exception as e:
            error_msg = f"Unexpected error in check_and_click: {e}"
            log_message(error_msg, LOG_PATH)
            print(f"Error: {error_msg}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            # Return NO_BUTTON to continue the loop without crashing
            return "NO_BUTTON"

    def run_loop(
        self,
        check_interval: int = 60,
        rate_limit_cooldown: int = 1200,
    ) -> None:
        """
        Run the agent in a continuous loop.

        Args:
            check_interval: Seconds between checks (default: 60)
            rate_limit_cooldown: Seconds to wait after rate limit (default: 1200 = 20 min)
        """
        log_message("Starting Desktop Auto-Allow Agent loop...", LOG_PATH)
        log_message(f"Check interval: {check_interval}s, Rate limit cooldown: {rate_limit_cooldown}s", LOG_PATH)

        try:
            while True:
                try:
                    status = self.check_and_click()
                except Exception as e:
                    log_message(f"Error in check_and_click loop: {e}", LOG_PATH)
                    status = "NO_BUTTON"  # Continue loop on error

                # Determine next wait time
                if status == "RATE_LIMITED":
                    wait_time = rate_limit_cooldown
                else:
                    wait_time = check_interval

                log_message(f"Next check in {wait_time} seconds...", LOG_PATH)
                time.sleep(wait_time)

        except KeyboardInterrupt:
            log_message("Agent loop stopped by user.", LOG_PATH)
        except Exception as e:
            log_message(f"Unexpected error in agent loop: {e}", LOG_PATH)
            import traceback
            import sys
            traceback.print_exc(file=sys.stderr)


def main() -> None:
    """Entry point for the Desktop Auto-Allow Agent."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Desktop Auto-Allow Agent using OpenAI Computer Use"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually click, just log what would happen",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between checks (default: 60)",
    )
    parser.add_argument(
        "--rate-limit-cooldown",
        type=int,
        default=1200,
        help="Seconds to wait after rate limit detected (default: 1200 = 20 min)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for testing)",
    )
    parser.add_argument(
        "--monitors",
        type=str,
        help="Comma-separated monitor indices to capture (e.g., '0,2' for left and right). Default: all monitors",
    )
    parser.add_argument(
        "--quadrant",
        type=str,
        choices=["bottom-left", "bottom-right", "top-left", "top-right", 
                 "right-half", "left-half", "top-half", "bottom-half"],
        help="Capture only the specified region: quadrants (1/4 size) or halves (1/2 size)",
    )

    args = parser.parse_args()

    # Parse monitor indices
    monitor_indices = None
    if args.monitors:
        try:
            monitor_indices = [int(x.strip()) for x in args.monitors.split(",")]
        except ValueError:
            print("Error: --monitors must be comma-separated integers (e.g., '0,2')")
            return

    try:
        agent = AutoAllowAgent(
            dry_run=args.dry_run,
            monitor_indices=monitor_indices,
            quadrant=args.quadrant
        )

        if args.once:
            status = agent.check_and_click()
            print(f"Status: {status}")
        else:
            agent.run_loop(
                check_interval=args.interval,
                rate_limit_cooldown=args.rate_limit_cooldown,
            )

    except ValueError as e:
        print(f"Error: {e}")
        print("\nPlease set your OpenAI API key:")
        print("  $env:OPENAI_API_KEY = 'your-api-key-here'")
        return
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise


if __name__ == "__main__":
    main()
