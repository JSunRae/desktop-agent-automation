# Pause and Desktop Switching Guide

## New Features Overview

The auto-clicker now includes four powerful features:
1. **Auto-pause on typing** - Automatically pauses when you're typing 🆕
2. **Pause/Resume functionality** - Manually pause/resume the automation
3. **Extra wait command** - Add a 20-second pause on demand
4. **Desktop switching** - Work across multiple virtual desktops

---

## ⌨️ Auto-Pause on Typing Feature (NEW!)

### How It Works
- **Automatically detects** when you're typing on your keyboard
- **Pauses automation** immediately when keyboard activity is detected
- **Resumes automatically** after 3 seconds of no typing (configurable)
- **No manual intervention needed** - works seamlessly in the background

### Configuration
```python
AUTO_PAUSE_ON_TYPING = True     # Enable/disable auto-pause
TYPING_IDLE_SECONDS = 3.0       # Resume after this many seconds of inactivity
```

### When to Use
- **Always keep it enabled** - it's non-intrusive and smart
- Prevents automation from interfering while you type
- Perfect for active coding sessions with Copilot
- Works alongside manual pause - you can still use Ctrl+Shift+P

### Status Messages
```
⌨️  Typing detected - auto-paused
✓ Typing idle - resuming automation
```

### To Disable
Set `AUTO_PAUSE_ON_TYPING = False` in the configuration section.

---

## 🎯 Manual Pause/Resume Feature

### How to Use
- **Press `Ctrl+Shift+P`** to pause the automation
- **Press `Ctrl+Shift+P`** again to resume

### When to Use
- When you need to temporarily stop automation while working
- Before demonstrating something or sharing your screen
- When testing or debugging other features

### What Happens When Paused
- The script continues running but skips all checks
- A message displays: `*** PAUSED ***`
- Press the hotkey again to resume normal operation

---

## ⏱️ Extra Wait Feature

### How to Use
- **Press `Ctrl+Shift+W`** to wait an additional 20 seconds

### When to Use
- When you're in the middle of reviewing something
- To give yourself time to read chat confirmations
- Before the automation clicks a button you want to examine

### Configurable Duration
Change the wait time by editing this line in the script:
```python
EXTRA_PAUSE_SECONDS = 20  # Change to any number of seconds you want
```

---

## 🖥️ Desktop Switching Feature

### Configuration

At the top of `auto_allow_copilot.py`, find this configuration:

```python
# Desktop configuration
# Set to "auto" to automatically detect which desktops have VS Code (recommended)
# Set to [0] to only check current desktop (no switching)
# Set to [1, 2, 3] to manually specify desktops to check
DESKTOPS_TO_CHECK = "auto"  # "auto" = auto-detect (recommended!)
```

### How to Enable Desktop Switching

**Option 1: Auto-Detect (Recommended!) 🆕**
```python
DESKTOPS_TO_CHECK = "auto"  # Automatically finds desktops with VS Code
```
- Scans all desktops at startup
- Only monitors desktops that have VS Code windows open
- Most efficient and convenient option
- No need to manually configure desktop numbers

**Option 2: Manually Specify Desktops**
```python
DESKTOPS_TO_CHECK = [1, 2, 3]  # Checks desktops 1, 2, and 3
```

**Option 3: Check Specific Desktops**
```python
DESKTOPS_TO_CHECK = [2, 4]  # Only checks desktops 2 and 4
```

**Option 4: Current Desktop Only**
```python
DESKTOPS_TO_CHECK = [0]  # No desktop switching
```

### How Auto-Detection Works 🆕

When `DESKTOPS_TO_CHECK = "auto"`:
1. **Startup scan**: The script scans all desktops (up to 10) at startup
2. **VS Code detection**: Identifies which desktops have VS Code windows open
3. **Smart list**: Creates a list of only those desktops that need monitoring
4. **Efficient cycling**: During operation, only switches between desktops that have VS Code

**Example output:**
```
[2025-11-23 ...] Scanning desktops for VS Code windows...
  ✓ Desktop 1: Found 3 VS Code window(s)
  ✓ Desktop 3: Found 2 VS Code window(s)
  ✓ Desktop 5: Found 1 VS Code window(s)
[2025-11-23 ...] Auto-detected desktops: [1, 3, 5]
Working on: Desktops [1, 3, 5]
```

### How Manual Desktop Switching Works

When manually configured (e.g., `[1, 2, 3]`):
1. The script cycles through each desktop in the list
2. Switches to that desktop (Windows 10/11 virtual desktops)
3. Searches for VS Code windows on that desktop
4. Clicks any Allow/Keep Edits buttons found
5. Moves to the next desktop in the list
6. Repeats the cycle

### Important Notes

- **Desktop numbers are 1-based**: Desktop 1 is your first desktop, Desktop 2 is second, etc.
- **Windows 10/11 only**: Uses virtual desktop features
- **Brief delay**: There's a short pause (0.8s default) when switching to allow the animation to complete
- **Max 10 desktops**: Can scan up to 10 desktops (configurable via `MAX_DESKTOPS_TO_SCAN`)
- **Auto-detect is smart**: If no VS Code windows found anywhere, falls back to current desktop only

---

## ⚙️ Customizing Hotkeys

If the default hotkeys conflict with other applications, change them in the configuration section:

```python
# Hotkey configuration (change if these conflict with other apps)
PAUSE_HOTKEY = 'ctrl+shift+p'       # hotkey to toggle pause/resume
EXTRA_WAIT_HOTKEY = 'ctrl+shift+w'  # hotkey to wait extra time
```

### Available Key Combinations

Examples of alternative hotkeys:
- `'ctrl+alt+p'`
- `'ctrl+shift+space'`
- `'f9'` (single key)
- `'ctrl+f12'`

See [keyboard library docs](https://github.com/boppreh/keyboard#api) for more options.

---

## 📋 Example Use Cases

### Use Case 1: Multi-Desktop Development (Auto-Detect) 🆕
You have VS Code open on multiple desktops with different projects:
```python
DESKTOPS_TO_CHECK = "auto"
```
At startup, the script scans and finds VS Code on desktops 1, 3, and 5. It will automatically cycle through only those three desktops, clicking Allow buttons wherever needed. No manual configuration required!

### Use Case 2: Multi-Desktop Development (Manual)
You know exactly which desktops have VS Code:
```python
DESKTOPS_TO_CHECK = [1, 2, 3]
```
The automation will cycle through all three, clicking Allow buttons wherever needed.

### Use Case 3: Pause During Presentation
You're sharing your screen and don't want the automation clicking during a demo:
1. Press `Ctrl+Shift+P` to pause
2. Do your presentation
3. Press `Ctrl+Shift+P` again to resume

### Use Case 4: Need More Time to Review
You see a command confirmation popup and want to read it before it's clicked:
1. Press `Ctrl+Shift+W` to add 20 seconds
2. Review the command
3. Automation resumes after the wait period

---

## 🚨 Troubleshooting

### Hotkeys Not Working
- **Run as Administrator**: Keyboard hotkeys may require admin privileges
- **Check conflicts**: Make sure another application isn't using the same hotkey
- **Try different keys**: Change the hotkey configuration if needed

### Desktop Switching Not Working
- **Windows 10/11 required**: Virtual desktops are a Windows 10/11 feature
- **Try auto-detect**: Use `DESKTOPS_TO_CHECK = "auto"` instead of manual configuration
- **Verify desktop order**: The script assumes your desktops are in sequential order
- **Check Task View**: Open Task View (Win+Tab) to verify your desktop layout
- **Adjust scan timing**: Increase `DESKTOP_SCAN_WAIT` if desktops switch too fast

### Still Having Issues?
- Check the terminal output for error messages
- Verify the `keyboard` package is installed: `pip install keyboard`
- Try running the script as administrator

---

## 🔧 All Configuration Options

```python
# Timing
CHECK_INTERVAL_SECONDS = 30      # How often to check for buttons
COOLDOWN_MINUTES = 20            # Wait after rate limit detected
EXTRA_PAUSE_SECONDS = 20         # Extra wait duration

# Auto-pause on typing
AUTO_PAUSE_ON_TYPING = True      # Enable auto-pause when typing
TYPING_IDLE_SECONDS = 3.0        # Resume after N seconds idle

# Hotkeys
PAUSE_HOTKEY = 'ctrl+shift+p'    # Toggle pause
EXTRA_WAIT_HOTKEY = 'ctrl+shift+w'  # Trigger extra wait

# Desktops
DESKTOPS_TO_CHECK = "auto"       # "auto" = auto-detect (recommended!)
                                 # [0] = current only
                                 # [1,2,3] = manual list
```

---

## 💡 Tips

1. **Keep auto-pause enabled** - it's the most intelligent feature and prevents interference
2. **Adjust idle time** if needed - 3 seconds works well, but customize for your typing speed
3. **Start with current desktop only** (`[0]`) and test the pause features first
4. **Add desktops gradually** - start with 2 desktops, then expand
5. **Use extra wait liberally** - it's safer to wait longer than to miss reviewing a command
6. **Keep Task View open** (Win+Tab) to visualize which desktop you're on
7. **Assign one VS Code window per desktop** for better organization

---

## Status Display

When running, you'll see messages like:
```
Hotkeys registered:
  ctrl+shift+p - Toggle pause/resume
  ctrl+shift+w - Wait extra 20 seconds

Desktop mode: Checking desktops [1, 2, 3]

[2025-11-23 ...] Found 2 VS Code window(s)
[2025-11-23 ...] Found Allow button in 'main.py - Visual Studio Code'
...

*** PAUSED ***  (when you press Ctrl+Shift+P)

[2025-11-23 ...] Extra wait (18s left)...  (after Ctrl+Shift+W)
```
ccc