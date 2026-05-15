# Desktop Auto-Allow Agent - System Prompt Documentation

This document contains the exact system prompt used by the Desktop Auto-Allow Agent when calling OpenAI's Computer Use API.

## System Prompt (Current Implementation)

The prompt has been streamlined for the `computer-use-preview` model, which already understands computer interaction patterns:

```
You are operating on a Windows desktop with Visual Studio Code open.

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

Be conservative. When in doubt, do nothing.
```

### Why the Shorter Prompt?

The `computer-use-preview` model is specifically trained for computer interaction tasks. It already understands:
- How to use the computer use tool
- How to identify clickable elements
- Coordinate systems and screen interactions
- Safety considerations for desktop automation

The prompt only needs to specify:
1. **What to look for** (Copilot approval buttons)
2. **What NOT to do** (safety constraints)
3. **How to report status** (the three status lines)

## Implementation Notes

### Model Usage
- Primary model: `AUTO_ALLOW_COMPUTER_USE_MODEL` (default `computer-use-preview`, via Responses API)
- Fallback model: `AUTO_ALLOW_VISION_FALLBACK_MODEL` (default `gpt-4o`, via Chat Completions API)
- **NOT** using Chat Completions API
- Requires the `computer_use_preview` tool configuration

### Request Structure
Each API call uses the **Responses API** format:
```python
response = client.responses.create(
    model=AUTO_ALLOW_COMPUTER_USE_MODEL,
    tools=[{
        "type": "computer_use_preview",
        "display_width": <screen_width>,
        "display_height": <screen_height>,
        "environment": "windows"
    }],
    input=[{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "<system_prompt + task>"},
            {"type": "input_image", "image_url": "data:image/png;base64,<screenshot>"}
        ]
    }],
    reasoning={"summary": "concise"},
    truncation="auto"
)
```

### Response Parsing
The agent processes `response.output` items:
1. **`computer_call` items**: Extract structured action (type, x, y coordinates)
2. **`text` items**: Check for status lines (CLICKED, NO_BUTTON, RATE_LIMITED)
3. **Execute action**: If `action.type == "click"`, use `pyautogui.click(x, y)`

No text parsing needed - coordinates come directly from the structured response.

### Scheduling Logic (External to Model)
- **Normal operation**: Check every 60 seconds (configurable)
- **Rate limited**: Wait 20 minutes before next check
- **Continuous loop**: Runs until manually stopped with Ctrl+C

### Safety Mechanisms
The system prompt emphasizes:
- Conservative clicking (only on confirmed Copilot buttons)
- No interaction with system UI or window controls
- Single action per invocation
- Clear status reporting

## Customization

To modify the agent's behavior:
1. Edit `SYSTEM_PROMPT` in `automation/desktop_auto_allow_agent.py`
2. Adjust button text patterns in section 1A
3. Modify rate limit detection patterns in section 1B
4. Update safety rules in section 2 as needed

## Testing Recommendations

Before using in production:
1. Run with `--dry-run --once` to verify detection
2. Monitor logs in `automation/auto_allow.log`
3. Test with various Copilot UI states
4. Verify it correctly identifies rate limiting messages
5. Ensure it doesn't click on unrelated UI elements
