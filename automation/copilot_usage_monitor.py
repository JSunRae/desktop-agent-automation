"""Monitor Copilot status from VS Code via UI Automation."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

import uiautomation as auto

from automation.cost_tracker import CostTracker, get_cost_tracker
from automation.utils import log_message


@dataclass
class CopilotStatusSnapshot:
    """Captures the latest Copilot usage observation."""

    timestamp: datetime
    percentage: Optional[float]
    calendar_progress: float
    normalized_ratio: Optional[float]
    alert: Optional[str]
    control_name: Optional[str]
    automation_id: Optional[str]


class CopilotUsageMonitor:
    """Polls the Copilot status bar entry and records normalized usage."""

    def __init__(
        self,
        *,
        root_provider: Callable[[], auto.Control] = lambda: auto.GetRootControl(),
        cost_tracker: Optional[CostTracker] = None,
        logger: Callable[[str], None] = lambda message: log_message(message),
        warning_threshold: float = 1.0,
        critical_threshold: float = 1.25,
        time_provider: Callable[[], datetime] = datetime.now,
        max_search_depth: int = 6,
    ) -> None:
        if warning_threshold > critical_threshold:
            raise ValueError("warning_threshold must be <= critical_threshold")

        self.root_provider = root_provider
        self.cost_tracker = cost_tracker
        self.logger = logger
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.time_provider = time_provider
        self.max_search_depth = max_search_depth

    def poll_once(self) -> CopilotStatusSnapshot:
        """Read the Copilot status percentage, normalize, log, and record it."""

        now = self.time_provider()
        progress_fraction = self._calendar_progress_fraction(now)
        control = self._find_status_control(self.root_provider(), self.max_search_depth)
        percentage = self._extract_percentage(control)
        normalized_ratio = None
        alert = None

        if percentage is not None:
            normalized_ratio = self._normalize_against_progress(percentage, progress_fraction)
            alert = self._evaluate_alert(normalized_ratio)
            if alert:
                self.logger(
                    f"[Copilot Usage] {alert} (normalized={normalized_ratio:.2f}, percent={percentage:.1f})"
                )

        snapshot = CopilotStatusSnapshot(
            timestamp=now,
            percentage=percentage,
            calendar_progress=progress_fraction * 100,
            normalized_ratio=normalized_ratio,
            alert=alert,
            control_name=getattr(control, "Name", None) if control else None,
            automation_id=getattr(control, "AutomationId", None) if control else None,
        )

        tracker = self.cost_tracker or get_cost_tracker()
        tracker.record_copilot_status(
            percentage=percentage,
            normalized_ratio=normalized_ratio,
            calendar_progress=snapshot.calendar_progress,
            alert=alert,
            timestamp=snapshot.timestamp,
            details={
                "control_name": snapshot.control_name,
                "automation_id": snapshot.automation_id,
            },
        )

        return snapshot

    def _calendar_progress_fraction(self, when: datetime) -> float:
        first = when.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = calendar.monthrange(when.year, when.month)[1]
        last = first + timedelta(days=days_in_month)
        total_seconds = (last - first).total_seconds()
        if total_seconds <= 0:
            return 0.0
        elapsed_seconds = max(0.0, (when - first).total_seconds())
        return min(1.0, elapsed_seconds / total_seconds)

    def _normalize_against_progress(self, percentage: float, progress_fraction: float) -> float:
        progress_percent = max(progress_fraction * 100, 1e-6)
        return percentage / progress_percent

    def _evaluate_alert(self, normalized_ratio: Optional[float]) -> Optional[str]:
        if normalized_ratio is None:
            return None
        if normalized_ratio >= self.critical_threshold:
            return "CRITICAL: Copilot usage pace exceeds calendar progress"
        if normalized_ratio >= self.warning_threshold:
            return "WARNING: Copilot usage pace is above calendar progress"
        return None

    def _find_status_control(
        self,
        control: Optional[auto.Control],
        depth: int,
    ) -> Optional[auto.Control]:
        if control is None or depth < 0:
            return None
        if self._is_copilot_status_control(control):
            return control
        children = self._safe_get_children(control)
        for child in children:
            hit = self._find_status_control(child, depth - 1)
            if hit is not None:
                return hit
        return None

    def _safe_get_children(self, control: auto.Control) -> list[auto.Control]:
        try:
            return list(control.GetChildren() or [])
        except Exception:
            return []

    def _is_copilot_status_control(self, control: auto.Control) -> bool:
        name = (getattr(control, "Name", None) or "").lower()
        automation_id = (getattr(control, "AutomationId", None) or "").lower()
        return "copilot status" in name or automation_id == "chat.statusbarentry"

    def _extract_percentage(self, control: Optional[auto.Control]) -> Optional[float]:
        if control is None:
            log_message("[Copilot Usage] Copilot status control not found")
            return None
        text = (getattr(control, "Name", None) or "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if not match:
            log_message("[Copilot Usage] Unable to parse percentage from status text")
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None