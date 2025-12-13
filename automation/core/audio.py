"""
Audio feedback utilities - beeps, text-to-speech, console flashing.

These provide audio/visual feedback to the user about automation state
without requiring them to watch the console.
"""

from __future__ import annotations

import ctypes
import subprocess


def beep(frequency: int = 800, duration: int = 100) -> None:
    """
    Play a short beep sound for audio feedback.
    
    Args:
        frequency: Tone frequency in Hz (default 800)
        duration: Duration in milliseconds (default 100)
    """
    try:
        ctypes.windll.kernel32.Beep(frequency, duration)
    except Exception:
        pass


def speak(text: str) -> None:
    """
    Use Windows text-to-speech to speak a message.
    
    Uses PowerShell's built-in speech synthesis with English voice.
    Runs asynchronously so it doesn't block automation.
    
    Args:
        text: Text to speak aloud
    """
    try:
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


def flash_console() -> None:
    """
    Flash the console window to get user's attention.
    
    Uses Win32 FlashWindow API.
    """
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.FlashWindow(hwnd, True)
    except Exception:
        pass


def play_pause_sound() -> None:
    """Play a low tone indicating pause."""
    beep(600, 200)


def play_resume_sound() -> None:
    """Play ascending tones indicating resume."""
    beep(1000, 100)
    beep(1200, 100)


def play_extra_wait_sound() -> None:
    """Play double beep indicating extra wait activated."""
    beep(800, 100)
    beep(800, 100)


def play_warning_sound() -> None:
    """Play descending tones indicating a warning."""
    beep(600, 300)
    beep(400, 300)
