"""
Monitor rate of Allow clicks and alert if it drops significantly.
"""

from datetime import datetime, timedelta
from typing import Optional

from automation.rate_limit.tracker import get_event_count_since, get_hourly_rate
from automation.core.audio import speak
from automation.notifications import send_telegram_alert
from automation.core.logging import log_normal

class RateMonitor:
    def __init__(self, check_interval_minutes: int = 5):
        self.last_check = datetime.now()
        self.check_interval = timedelta(minutes=check_interval_minutes)
        self.last_alert_time = datetime.min
        self.alert_cooldown = timedelta(minutes=30)
        
        self.session_peak_rate = 0.0
        self.last_resume_time = datetime.now()
        self.was_paused = False
        
    def update_pause_state(self, is_paused: bool):
        if is_paused and not self.was_paused:
            # Just paused
            pass
        elif not is_paused and self.was_paused:
            # Just resumed
            self.last_resume_time = datetime.now()
        
        self.was_paused = is_paused

    def check(self, is_paused: bool) -> None:
        """
        Check rate conditions and trigger alerts if needed.
        Should be called regularly in the main loop.
        """
        now = datetime.now()
        self.update_pause_state(is_paused)
        
        if is_paused:
            return

        # Check interval
        if now - self.last_check < self.check_interval:
            return
        self.last_check = now

        # Time window check (10am - 10pm)
        if not (10 <= now.hour < 22):
            return

        # Calculate current effective rate
        # If we resumed recently (< 60 mins ago), we project the rate
        time_since_resume = (now - self.last_resume_time).total_seconds() / 60.0
        
        current_rate = 0.0
        if time_since_resume < 10:
             # Warmup period - too jittery to alert
             return
        elif time_since_resume < 60:
             # Projected rate based on current session
             count = get_event_count_since(self.last_resume_time)
             current_rate = count / (time_since_resume / 60.0)
        else:
             # Full hour history available
             current_rate = float(get_hourly_rate())

        # Update peak rate
        if current_rate > self.session_peak_rate:
            self.session_peak_rate = current_rate

        # Check conditions
        should_alert = False
        reason = ""

        # Condition 1: Rate < 20/hr
        if current_rate < 20:
             should_alert = True
             reason = f"Rate is low ({current_rate:.1f} clicks/hr)"

        # Condition 2: Drop > 70% from peak
        # Only check this if peak was significant (e.g., > 30) to avoid noise at low rates
        if self.session_peak_rate > 30:
            if current_rate < (self.session_peak_rate * 0.3):
                should_alert = True
                reason = f"Rate dropped >70% (Current: {current_rate:.1f}, Peak: {self.session_peak_rate:.1f})"
        
        if should_alert:
             self._trigger_alert(reason)

    def _trigger_alert(self, reason: str) -> None:
        now = datetime.now()
        if now - self.last_alert_time < self.alert_cooldown:
            return
        
        self.last_alert_time = now
        message = f"⚠️ Automation Alert: {reason}. Activate more agents."
        log_normal(message)
        
        # Actions
        try:
            speak("Activate more agents")
            send_telegram_alert(message)
        except Exception as e:
            log_normal(f"Error executing alert actions: {e}")
