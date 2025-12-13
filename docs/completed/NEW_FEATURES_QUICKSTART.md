# Quick Start - New Features

## 🎯 Four New Features Added

### 1. Auto-Pause on Typing 🆕
- **Automatic**: No hotkey needed
- **Usage**: Simply start typing - automation pauses automatically
- **Resumes**: After 3 seconds of idle (configurable)
- **Status**: Shows "⌨️ Typing detected - auto-paused" when active

### 2. Manual Pause/Resume Button
- **Hotkey**: `Ctrl+Shift+P`
- **Usage**: Press to pause automation, press again to resume
- **Status**: Shows "*** MANUAL PAUSED ***" message when active

### 3. Extra Wait Command
- **Hotkey**: `Ctrl+Shift+W`
- **Usage**: Press to wait an additional 20 seconds
- **Configurable**: Change `EXTRA_PAUSE_SECONDS = 20` at top of script

### 4. Desktop Switching with Auto-Detection
- **Default**: `[0]` - Works on current desktop only (recommended for most users!)
- **Auto-detect**: `"auto"` - Scans and finds all desktops with VS Code (advanced)
- **Manual**: Specify exact desktop numbers if you know them
  ```python
  DESKTOPS_TO_CHECK = [0]        # Current desktop only (recommended!)
  DESKTOPS_TO_CHECK = "auto"     # Auto-detect all VS Code desktops
  DESKTOPS_TO_CHECK = [1, 2, 3]  # Manually specify desktops
  ```

### 5. Master Prompt ➜ Copilot Panel Tester 🧪
- **What it does**: Calls the OpenAI API via the master orchestrator, then opens a brand-new Copilot chat panel and pastes the generated prompts automatically.
- **Script**: `automation/new_chat_prompt_tester.py`
- **Requirements**: Windows, Copilot Chat view visible, and `OPENAI_API_KEY` configured.
- **Usage**:
  ```powershell
  python automation/new_chat_prompt_tester.py
  ```
- **Options**:
  - `--reuse-latest` reuses `tasks/generated_prompts/latest.txt` so you can skip another API call.
  - `--dry-run` only generates (or loads) prompts without touching the UI.
  - `--docs <paths...>` points the orchestrator at custom document folders.
  - `--window-timeout` / `--panel-timeout` tune how long we wait for the Copilot UI elements.

## 🚀 How to Run

```powershell
python auto_allow_copilot.py
```

**Note**: For hotkeys to work properly, you may need to run as Administrator:
```powershell
# Right-click PowerShell and select "Run as Administrator", then:
python auto_allow_copilot.py
```

## ⚙️ Configuration (Top of Script)

```python
# Timing
CHECK_INTERVAL_SECONDS = 30      # Check every 30 seconds
EXTRA_PAUSE_SECONDS = 20         # Wait 20 seconds on Ctrl+Shift+W

# Auto-pause on typing (NEW!)
AUTO_PAUSE_ON_TYPING = True      # Enable auto-pause when typing
TYPING_IDLE_SECONDS = 3.0        # Resume after N seconds of idle

# Hotkeys (change if conflicts occur)
PAUSE_HOTKEY = 'ctrl+shift+p'    
EXTRA_WAIT_HOTKEY = 'ctrl+shift+w'

# Desktops ([0] = current, "auto" = detect, [1,2,3] = manual)
DESKTOPS_TO_CHECK = [0]          # Current desktop only (recommended!)
```

## 📖 Full Documentation

See `PAUSE_AND_DESKTOP_GUIDE.md` for detailed documentation including:
- Troubleshooting
- Use cases
- Customization options
- Tips and best practices
