"""
Session statistics tracking.

Tracks metrics for the current automation session:
- Start time and uptime
- Total clicks (Allow, Keep Edits)
- Rate limit count
- Provides summary output on shutdown
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any


@dataclass
class SessionStats:
    """
    Tracks statistics for the current automation session.
    
    Create one instance at startup and update it throughout the session.
    Call print_summary() before shutdown to display results.
    """
    
    # Session timing
    start_time: datetime = field(default_factory=datetime.now)
    
    # Click counts
    total_allow_clicks: int = 0
    total_keep_edits_clicks: int = 0
    
    # Rate limit tracking
    rate_limit_count: int = 0
    
    # Per-cycle metrics (reset each scan cycle)
    cycle_allow_clicks: int = 0
    cycle_keep_edits_clicks: int = 0
    cycle_vscode_windows: int = 0
    
    def record_allow_click(self, count: int = 1) -> None:
        """Record Allow button click(s)."""
        self.total_allow_clicks += count
        self.cycle_allow_clicks += count
    
    def record_keep_edits_click(self, count: int = 1) -> None:
        """Record Keep Edits button click(s)."""
        self.total_keep_edits_clicks += count
        self.cycle_keep_edits_clicks += count
    
    def record_rate_limit(self) -> None:
        """Record a rate limit detection."""
        self.rate_limit_count += 1
    
    def set_cycle_windows(self, count: int) -> None:
        """Set the number of VS Code windows seen this cycle."""
        self.cycle_vscode_windows = count
    
    def reset_cycle(self) -> None:
        """Reset per-cycle counters for a new scan cycle."""
        self.cycle_allow_clicks = 0
        self.cycle_keep_edits_clicks = 0
        self.cycle_vscode_windows = 0
    
    def get_cycle_metrics(self) -> Dict[str, int]:
        """Get current cycle metrics for logging."""
        return {
            "total_vscode_windows": self.cycle_vscode_windows,
            "allow_clicked_cycle": self.cycle_allow_clicks,
            "keep_edits_clicked_cycle": self.cycle_keep_edits_clicks,
        }
    
    def get_uptime_seconds(self) -> float:
        """Get session uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def format_duration(self, seconds: float) -> str:
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
    
    def print_summary(self) -> None:
        """Print a summary of session statistics."""
        now = datetime.now()
        uptime = self.get_uptime_seconds()
        
        print(f"\n{'='*60}")
        print("SESSION SUMMARY")
        print(f"{'='*60}")
        print(f"  Started:           {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Ended:             {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Uptime:            {self.format_duration(uptime)}")
        print(f"  Allow clicks:      {self.total_allow_clicks}")
        print(f"  Keep Edits clicks: {self.total_keep_edits_clicks}")
        print(f"  Rate limits hit:   {self.rate_limit_count}")
        if self.rate_limit_count > 0 and uptime > 0:
            avg_minutes = uptime / 60 / max(self.rate_limit_count, 1)
            print(f"  Avg time between:  {avg_minutes:.1f} minutes per rate limit")
        print(f"{'='*60}\n")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": self.get_uptime_seconds(),
            "total_allow_clicks": self.total_allow_clicks,
            "total_keep_edits_clicks": self.total_keep_edits_clicks,
            "rate_limit_count": self.rate_limit_count,
        }


# Global session instance (created on module load)
_session: SessionStats | None = None


def get_session() -> SessionStats:
    """Get or create the global session stats instance."""
    global _session
    if _session is None:
        _session = SessionStats()
    return _session


def reset_session() -> SessionStats:
    """Reset the global session stats (for testing or restart)."""
    global _session
    _session = SessionStats()
    return _session


def get_session_stats() -> Dict[str, Any]:
    """Get current session stats as a dictionary."""
    return get_session().to_dict()


def increment_allow_clicks(count: int = 1) -> None:
    """Increment Allow click count."""
    get_session().record_allow_click(count)


def increment_keep_edits_clicks(count: int = 1) -> None:
    """Increment Keep Edits click count."""
    get_session().record_keep_edits_click(count)


def increment_rate_limit_count() -> None:
    """Increment rate limit detection count."""
    get_session().record_rate_limit()
