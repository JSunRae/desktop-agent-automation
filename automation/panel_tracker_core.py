"""Core panel tracking logic.

This module holds the `PanelTracker` class and persistence/timing logic.
It deliberately avoids UI automation operations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from automation.config import (
    DEFAULT_REPO_PRIORITY_WEIGHT,
    MODEL_PRIORITY_WEIGHTS,
    REPO_PRIORITY_WEIGHTS,
)
from automation.feedback_analyzer import get_feedback_analyzer
from automation.metrics import get_metrics_tracker
from automation.panel_quality import get_panel_quality_analyzer
from automation.panel_task_dispatcher import DEFAULT_REPO_PROMPT_KEY
from automation.panel_state import (
    IdleReason,
    PanelState,
    PanelStatus,
    QualityStatus,
    TRANSCRIPT_FILTER_PLACEHOLDER,
    TRANSCRIPT_HASH_LEN,
    TRANSCRIPT_KIND_COMPLETION,
    TRANSCRIPT_MAX_SNAPSHOTS,
    TranscriptSnapshot,
    _preview_transcript_text,
    extract_repo_name_from_title,
)
from automation.panel_transcript_analysis import analyze_panel_transcripts
from automation.response_parser import ResponseCategory, classify_response


_REPO_PRIORITY_MAP = {key.lower(): value for key, value in REPO_PRIORITY_WEIGHTS.items()}
_MODEL_PRIORITY_MAP = {key.lower(): value for key, value in MODEL_PRIORITY_WEIGHTS.items()}
_STATUS_PRIORITY_BONUSES = {
    PanelStatus.WAITING_ALLOW: 5.0,
    PanelStatus.RATE_LIMITED: 4.0,
    PanelStatus.RUNNING: 3.0,
    PanelStatus.FINISHED: 2.0,
    PanelStatus.IDLE: 1.0,
    PanelStatus.COMPLETED: 0.5,
    PanelStatus.NEEDS_INPUT: 1.5,
    PanelStatus.ERROR: 2.5,
    PanelStatus.STALE: 0.25,
}
_TASK_AGE_DIVISOR_MINUTES = 15.0
_TASK_AGE_MAX_BONUS = 3.0


# Timing thresholds
PANEL_IDLE_THRESHOLD_MINUTES = 30      # Consider panel idle after this long without Allow/Keep clicks
PANEL_FINISHED_THRESHOLD_MINUTES = 30  # Consider panel finished if output unchanged for this long
PANEL_STALE_THRESHOLD_MINUTES = 60     # Consider panel stale if not scanned for this long (desktop unreachable)
OUTPUT_SAMPLE_CHARS = 100              # Number of characters to sample from end of output


DEFAULT_PANEL_STATE_PATH = Path(__file__).parent / "panel_state.json"


@dataclass
class PanelTracker:
    """Tracks all Copilot panels we've interacted with."""

    state_path: Path = DEFAULT_PANEL_STATE_PATH
    panels: Dict[str, PanelState] = field(default_factory=dict)
    next_prompt_index: int = 0  # Legacy round-robin index for backward compatibility
    repo_prompt_indices: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self._load_state()
        self._quality_analyzer = get_panel_quality_analyzer()
        self._feedback_analyzer = get_feedback_analyzer()

    def _generate_panel_key(self, window_title: str, panel_id: str = "") -> str:
        if panel_id:
            return f"{window_title}::{panel_id}"
        return window_title

    def build_panel_key(self, panel: PanelState) -> str:
        return self._generate_panel_key(panel.window_title, panel.panel_id)

    def _normalize_repo_key(self, repo_name: Optional[str]) -> str:
        return (repo_name or DEFAULT_REPO_PROMPT_KEY).lower()

    def _ensure_repo_counter(self, repo_name: Optional[str]) -> int:
        key = self._normalize_repo_key(repo_name)
        if key not in self.repo_prompt_indices:
            if key == DEFAULT_REPO_PROMPT_KEY and self.next_prompt_index:
                self.repo_prompt_indices[key] = self.next_prompt_index
            else:
                self.repo_prompt_indices[key] = 0
        return self.repo_prompt_indices[key]

    def refresh_priority_scores(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        for panel in self.panels.values():
            components = self._compute_priority_components(panel, now)
            panel.priority_components = components
            panel.priority_score = components["score"]

    def compute_window_priority_score(self, window_title: str, panel_id: str = "") -> float:
        key = self._generate_panel_key(window_title, panel_id)
        panel = self.panels.get(key)
        if panel is None:
            return 0.0
        if panel.priority_score == 0.0:
            components = self._compute_priority_components(panel, datetime.now())
            panel.priority_components = components
            panel.priority_score = components["score"]
        return panel.priority_score

    def sort_windows_by_priority(self, windows: List[Any]) -> List[Any]:
        ranked: List[tuple[float, int, Any]] = []
        for idx, window in enumerate(windows):
            try:
                title = window.Name or ""
            except Exception:
                continue
            score = self.compute_window_priority_score(title)
            ranked.append((-score, idx, window))
        ranked.sort()
        return [entry[2] for entry in ranked]

    def _compute_priority_components(self, panel: PanelState, now: datetime) -> Dict[str, float]:
        repo_weight = self._resolve_repo_weight(panel.repo_name)
        reference_time = panel.assignment_time or panel.last_allow_click
        age_minutes = max(0.0, (now - reference_time).total_seconds() / 60)
        age_bonus = min(age_minutes / _TASK_AGE_DIVISOR_MINUTES, _TASK_AGE_MAX_BONUS)

        attempts = max(panel.assignment_attempts, 0)
        success_rate = 0.5
        if attempts:
            success_rate = min(1.0, max(0.0, panel.assignment_successes / attempts))
        success_component = 0.75 + 0.5 * success_rate

        model_label = (panel.assigned_model_label or "").lower()
        model_weight = _MODEL_PRIORITY_MAP.get(model_label, 1.0)

        status_bonus = _STATUS_PRIORITY_BONUSES.get(panel.status, 0.5)
        if panel.idle_reason == IdleReason.WAITING_ALLOW:
            status_bonus += 1.0

        score = repo_weight * (1.0 + age_bonus) * success_component * model_weight + status_bonus

        return {
            "repo_weight": round(repo_weight, 3),
            "age_minutes": round(age_minutes, 2),
            "age_bonus": round(age_bonus, 3),
            "success_rate": round(success_rate, 3),
            "success_component": round(success_component, 3),
            "model_weight": round(model_weight, 3),
            "status_bonus": round(status_bonus, 3),
            "score": round(score, 3),
        }

    def _resolve_repo_weight(self, repo_name: Optional[str]) -> float:
        if not repo_name:
            return DEFAULT_REPO_PRIORITY_WEIGHT
        return _REPO_PRIORITY_MAP.get(repo_name.lower(), DEFAULT_REPO_PRIORITY_WEIGHT)

    def _record_assignment_success(self, panel: PanelState) -> None:
        task_id = panel.assigned_task_id
        if not task_id or panel.last_assignment_outcome_id == task_id:
            return
        panel.assignment_successes += 1
        panel.last_assignment_outcome_id = task_id

    def _record_assignment_failure(self, panel: PanelState) -> None:
        task_id = panel.assigned_task_id
        if not task_id or panel.last_assignment_outcome_id == task_id:
            return
        panel.assignment_failures += 1
        panel.last_assignment_outcome_id = task_id

    def _record_transcript_snapshot(self, panel: PanelState, *, kind: str, text: str) -> None:
        normalized = (text or "").strip()
        if not normalized:
            return

        digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
        short_hash = digest[:TRANSCRIPT_HASH_LEN]
        is_sensitive = self._is_response_sensitive(normalized)
        preview = None if is_sensitive else _preview_transcript_text(normalized)
        if is_sensitive:
            preview = TRANSCRIPT_FILTER_PLACEHOLDER

        snapshot = TranscriptSnapshot(
            kind=kind,
            timestamp=datetime.now(),
            content_hash=short_hash,
            preview=preview,
            filtered=is_sensitive,
            length=len(normalized),
        )

        if not isinstance(panel.transcript_snapshots, list):
            panel.transcript_snapshots = []

        if panel.transcript_snapshots:
            last_snapshot = panel.transcript_snapshots[-1]
            if last_snapshot.content_hash == snapshot.content_hash and last_snapshot.kind == snapshot.kind:
                last_snapshot.timestamp = snapshot.timestamp
                last_snapshot.length = snapshot.length
                last_snapshot.filtered = snapshot.filtered
                last_snapshot.preview = snapshot.preview
                return

        panel.transcript_snapshots.append(snapshot)
        if len(panel.transcript_snapshots) > TRANSCRIPT_MAX_SNAPSHOTS:
            panel.transcript_snapshots = panel.transcript_snapshots[-TRANSCRIPT_MAX_SNAPSHOTS:]

    def get_prompt_index_for_repo(self, repo_name: Optional[str], prompt_count: int) -> int:
        if prompt_count <= 0:
            return 0
        counter = self._ensure_repo_counter(repo_name)
        return counter % prompt_count

    def get_repo_prompt_counter(self, repo_name: Optional[str]) -> int:
        return self._ensure_repo_counter(repo_name)

    def advance_prompt_index(self, repo_name: Optional[str], *, steps: int = 1) -> None:
        if steps < 1:
            return
        key = self._normalize_repo_key(repo_name)
        current = self._ensure_repo_counter(repo_name) + steps
        self.repo_prompt_indices[key] = current
        if key == DEFAULT_REPO_PROMPT_KEY:
            self.next_prompt_index = current

    def _quality_status_hint(self, response_category: Optional[ResponseCategory]) -> QualityStatus:
        if response_category == ResponseCategory.COMPLETED:
            return QualityStatus.COMPLETED
        if response_category == ResponseCategory.ERROR:
            return QualityStatus.BLOCKED
        if response_category == ResponseCategory.ASKING_CLARIFICATION:
            return QualityStatus.NEEDS_REVISION
        return QualityStatus.IN_PROGRESS

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return

        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            for key, panel_data in data.get("panels", {}).items():
                try:
                    self.panels[key] = PanelState.from_dict(panel_data)
                except Exception as e:
                    print(f"  Warning: Could not load panel state for {key}: {e}")

            self.next_prompt_index = data.get("next_prompt_index", 0)
            raw_repo_indices = data.get("repo_prompt_indices", {})
            if isinstance(raw_repo_indices, dict):
                for repo_key, counter in raw_repo_indices.items():
                    try:
                        self.repo_prompt_indices[str(repo_key).lower()] = int(counter)
                    except (TypeError, ValueError):
                        continue
            if DEFAULT_REPO_PROMPT_KEY not in self.repo_prompt_indices and self.next_prompt_index:
                self.repo_prompt_indices[DEFAULT_REPO_PROMPT_KEY] = self.next_prompt_index

            if self.panels:
                print(f"[PanelTracker] Loaded {len(self.panels)} panels from previous session")
        except Exception as e:
            print(f"[PanelTracker] Warning: Could not load panel state: {e}")

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "saved_at": datetime.now().isoformat(),
                "next_prompt_index": self.next_prompt_index,
                "repo_prompt_indices": self.repo_prompt_indices,
                "panels": {key: panel.to_dict() for key, panel in self.panels.items()},
            }

            with self.state_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[PanelTracker] Warning: Could not save panel state: {e}")

    def record_allow_click(self, window_title: str, panel_id: str = "") -> None:
        now = datetime.now()
        key = self._generate_panel_key(window_title, panel_id)
        repo_name = extract_repo_name_from_title(window_title)

        if key in self.panels:
            panel = self.panels[key]
            panel.last_allow_click = now
            panel.last_scanned = now
            panel.status = PanelStatus.RUNNING
            panel.is_running = True
            if repo_name and panel.repo_name != repo_name:
                panel.repo_name = repo_name
            panel.sent_completion_check = False
            panel.sent_next_steps_response = False
        else:
            self.panels[key] = PanelState(
                window_title=window_title,
                panel_id=panel_id,
                first_seen=now,
                last_allow_click=now,
                last_output_change=now,
                repo_name=repo_name,
            )

        self._save_state()

    def update_panel_output(self, window_title: str, output_text: str, is_running: bool = False, panel_id: str = "") -> None:
        now = datetime.now()
        key = self._generate_panel_key(window_title, panel_id)

        if key not in self.panels:
            return

        panel = self.panels[key]
        repo_name = extract_repo_name_from_title(window_title)
        if repo_name and panel.repo_name != repo_name:
            panel.repo_name = repo_name

        panel.is_running = is_running
        panel.last_scanned = now

        if panel.status == PanelStatus.STALE:
            if is_running:
                panel.status = PanelStatus.RUNNING
                print(f"[PanelTracker] Panel back to RUNNING (was STALE, now verified): {window_title[:50]}")
            else:
                panel.status = PanelStatus.IDLE
                print(f"[PanelTracker] Panel back to IDLE (was STALE, now verified): {window_title[:50]}")

        new_sample = output_text[-OUTPUT_SAMPLE_CHARS:] if output_text else ""
        new_hash = hashlib.sha256(output_text.encode("utf-8", errors="ignore")).hexdigest()[:16]

        if new_hash != panel.last_output_hash:
            panel.last_output_change = now
            panel.last_output_sample = new_sample
            panel.last_output_hash = new_hash

            parsed = classify_response(new_sample)
            panel.last_response_category = parsed.category
            panel.last_response_confidence = parsed.confidence
            panel.last_response_evidence = parsed.evidence
            panel.last_response_secondary_categories = parsed.secondary_categories

            is_sensitive = self._is_response_sensitive(output_text)
            processing_time = None
            if panel.assignment_time:
                processing_time = (now - panel.assignment_time).total_seconds()

            get_metrics_tracker().record_response_feedback(
                panel_title=window_title,
                response_category=cast(Any, parsed.category),
                response_confidence=parsed.confidence,
                response_evidence=parsed.evidence,
                response_sample=new_sample,
                prompt_id=panel.assigned_prompt_id,
                prompt_preview=panel.assigned_prompt_text,
                is_sensitive=is_sensitive,
                processing_time_seconds=processing_time,
            )

            self._apply_response_category(panel, parsed.category, window_title, is_running)

            if parsed.category == ResponseCategory.COMPLETED:
                self._record_transcript_snapshot(panel, kind=TRANSCRIPT_KIND_COMPLETION, text=output_text)

            self._run_quality_analysis(panel, output_text)

            if panel.status in (PanelStatus.IDLE, PanelStatus.FINISHED):
                panel.status = PanelStatus.RUNNING
                print(f"[PanelTracker] Panel back to RUNNING (output changed): {window_title[:50]}")

            try:
                transcript_texts = [snap.preview for snap in panel.transcript_snapshots if snap.preview and not snap.filtered]
                analysis = analyze_panel_transcripts(
                    transcript_texts=transcript_texts,
                    latest_output=output_text,
                    status_hint=self._quality_status_hint(parsed.category),
                )
                panel.quality_assessment = analysis.assessment
                panel.quality_history.append(analysis.trend_entry)
                panel.quality_history = panel.quality_history[-20:]
                panel.transcript_issue_tags = analysis.issue_tags
                panel.transcript_issue_summary = analysis.summary
                panel.last_transcript_analysis = analysis.assessment.last_evaluated
                if analysis.assessment.needs_human_review:
                    panel.needs_human_review = True
                get_feedback_analyzer().record_transcript_analysis(panel, analysis)
            except Exception as exc:
                print(f"[PanelTracker] Transcript analysis failed: {exc}")

        self._save_state()

    def _is_response_sensitive(self, text: str) -> bool:
        if not text:
            return False

        lower_text = text.lower()
        sensitive_patterns = [
            r"\b(password|passwd|pwd)\b",
            r"\b(api\s*key|apikey)\b",
            r"\b(secret|token|auth)\b",
            r"\b(credit\s*card|card\s*number)\b",
            r"\b(ssn|social\s*security)\b",
            r"\b(email|mail)\s*[:=]\s*[\w\.-]+@[\w\.-]+\.\w+",
            r"\b(phone|mobile|tel)\s*[:=]\s*[\d\s\-\(\)\+]+",
            r"\b(ip\s*address|ipaddr)\b",
            r"\b(private\s*key|public\s*key)\b",
            r"\b(database\s*url|db\s*url)\b",
            r"\b(connection\s*string)\b",
        ]

        import re

        for pattern in sensitive_patterns:
            if re.search(pattern, lower_text):
                return True

        return False

    def _apply_response_category(self, panel: PanelState, category: ResponseCategory, window_title: str, is_running: bool) -> None:
        if category == ResponseCategory.COMPLETED:
            if panel.status != PanelStatus.COMPLETED:
                panel.status = PanelStatus.COMPLETED
                panel.idle_reason = None
                print(f"[PanelTracker] Panel marked COMPLETED by parser: {window_title[:50]}")
            return

        if category == ResponseCategory.ASKING_CLARIFICATION:
            if panel.status != PanelStatus.NEEDS_INPUT:
                panel.status = PanelStatus.NEEDS_INPUT
                panel.idle_reason = IdleReason.AWAITING_USER
                print(f"[PanelTracker] Panel needs input: {window_title[:50]}")
            return

        if category == ResponseCategory.ERROR:
            if panel.status != PanelStatus.ERROR:
                panel.status = PanelStatus.ERROR
                panel.idle_reason = None
                print(f"[PanelTracker] Panel flagged ERROR: {window_title[:50]}")
            self._record_assignment_failure(panel)
            return

        if category == ResponseCategory.SUGGESTING_NEXT_STEPS:
            if panel.status not in (PanelStatus.FINISHED, PanelStatus.COMPLETED):
                panel.status = PanelStatus.FINISHED
                panel.idle_reason = IdleReason.POSSIBLY_FINISHED
                print(f"[PanelTracker] Panel suggests next steps: {window_title[:50]}")
            return

        if panel.status in (PanelStatus.NEEDS_INPUT, PanelStatus.ERROR):
            next_status = PanelStatus.RUNNING if is_running else PanelStatus.IDLE
            panel.status = next_status
            panel.idle_reason = None
            print(f"[PanelTracker] Panel cleared special status: {window_title[:50]} -> {next_status.value}")

    def update_panel_status(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        idle_threshold = now - timedelta(minutes=PANEL_IDLE_THRESHOLD_MINUTES)
        finished_threshold = now - timedelta(minutes=PANEL_FINISHED_THRESHOLD_MINUTES)
        stale_threshold = now - timedelta(minutes=PANEL_STALE_THRESHOLD_MINUTES)

        for _key, panel in self.panels.items():
            if panel.status == PanelStatus.COMPLETED:
                continue

            if panel.last_scanned < stale_threshold:
                if panel.status in (PanelStatus.RUNNING, PanelStatus.IDLE, PanelStatus.WAITING_ALLOW):
                    old_status = panel.status
                    panel.status = PanelStatus.STALE
                    mins_since_scan = int((now - panel.last_scanned).total_seconds() / 60)
                    print(
                        f"[PanelTracker] Panel now STALE (was {old_status.value}, not scanned for {mins_since_scan}min): "
                        f"{panel.window_title[:50]}"
                    )
                continue

            if panel.status in (PanelStatus.NEEDS_INPUT, PanelStatus.ERROR):
                continue

            if panel.is_running:
                panel.status = PanelStatus.RUNNING
                continue

            if panel.last_allow_click < idle_threshold:
                if panel.status == PanelStatus.RUNNING:
                    panel.status = PanelStatus.IDLE
                    print(
                        f"[PanelTracker] Panel now IDLE (no Allow clicks for {PANEL_IDLE_THRESHOLD_MINUTES}min): "
                        f"{panel.window_title[:50]}"
                    )

            if panel.status == PanelStatus.IDLE:
                if panel.last_output_change < finished_threshold:
                    panel.status = PanelStatus.FINISHED
                    print(
                        f"[PanelTracker] Panel now FINISHED (output unchanged for {PANEL_FINISHED_THRESHOLD_MINUTES}min): "
                        f"{panel.window_title[:50]}"
                    )

        self._save_state()

    def _run_quality_analysis(self, panel: PanelState, transcript_text: str) -> None:
        if not transcript_text:
            return
        analyzer = getattr(self, "_quality_analyzer", None)
        if analyzer is None:
            return
        try:
            assessment = analyzer.evaluate_panel(panel, transcript_text, panel.assigned_prompt_text)
            feedback = getattr(self, "_feedback_analyzer", None)
            if feedback is not None:
                feedback.record_quality_assessment(panel, assessment)
        except Exception as exc:
            print(f"[PanelTracker] Quality analysis error for {panel.window_title[:50]}: {exc}")

    def get_finished_panels_needing_attention(self) -> List[PanelState]:
        result: List[PanelState] = []
        for panel in self.panels.values():
            if panel.status != PanelStatus.FINISHED:
                continue

            output_lower = panel.last_output_sample.lower()
            has_next_steps = (
                panel.last_response_category == ResponseCategory.SUGGESTING_NEXT_STEPS
                or "next steps" in output_lower
                or "next step" in output_lower
            )

            if has_next_steps and not panel.sent_next_steps_response:
                result.append(panel)
            elif not panel.sent_completion_check:
                result.append(panel)

        return result

    def get_panel_priority(self, window_title: str, panel_id: str = "") -> int:
        key = self._generate_panel_key(window_title, panel_id)
        if key not in self.panels:
            return 0

        panel = self.panels[key]

        if panel.status == PanelStatus.RUNNING:
            return 0
        if panel.status in (PanelStatus.WAITING_ALLOW, PanelStatus.RATE_LIMITED):
            return 0
        if panel.status in (PanelStatus.NEEDS_INPUT, PanelStatus.ERROR):
            return 0
        if panel.status == PanelStatus.IDLE:
            return 1
        if panel.status == PanelStatus.FINISHED:
            return 2
        if panel.status == PanelStatus.COMPLETED:
            return 3
        if panel.status == PanelStatus.STALE:
            return 4
        return 3

    def mark_completion_check_sent(self, window_title: str, panel_id: str = "") -> None:
        key = self._generate_panel_key(window_title, panel_id)
        if key in self.panels:
            self.panels[key].sent_completion_check = True
            self.panels[key].times_checked += 1
            self._save_state()

    def mark_next_steps_response_sent(self, window_title: str, panel_id: str = "") -> None:
        key = self._generate_panel_key(window_title, panel_id)
        if key in self.panels:
            self.panels[key].sent_next_steps_response = True
            self._save_state()

    def mark_completed(self, window_title: str, panel_id: str = "", completion_text: Optional[str] = None) -> None:
        key = self._generate_panel_key(window_title, panel_id)
        if key in self.panels:
            panel = self.panels[key]
            panel.status = PanelStatus.COMPLETED
            if completion_text:
                self._record_transcript_snapshot(panel, kind=TRANSCRIPT_KIND_COMPLETION, text=completion_text)
            self._record_assignment_success(panel)
            print(f"[PanelTracker] Panel marked COMPLETED: {window_title[:50]}")
            self._save_state()

    def get_live_panels(self) -> List[PanelState]:
        return [p for p in self.panels.values() if p.status == PanelStatus.RUNNING]

    def get_finished_panels(self) -> List[PanelState]:
        return [p for p in self.panels.values() if p.status == PanelStatus.FINISHED]

    def get_finished_panels_for_seeding(self, now: Optional[datetime] = None) -> List[PanelState]:
        """Return finished panels that are eligible for prompt seeding.

        This applies exponential backoff to panels that previously failed
        seeding so we don't thrash on problematic windows.
        """
        now = now or datetime.now()
        result: List[PanelState] = []
        for panel in self.panels.values():
            if panel.status != PanelStatus.FINISHED:
                continue
            if panel.seeded_prompt:
                continue

            # If no prior failures, panel is immediately eligible.
            if panel.seed_retry_count <= 0:
                result.append(panel)
                continue

            # If we marked it as needing retry, honour the next_retry_at gate.
            next_retry_at = panel.seed_next_retry_at
            if panel.needs_retry and next_retry_at and next_retry_at > now:
                continue

            result.append(panel)

        return result

    def get_completed_panels(self) -> List[PanelState]:
        return [p for p in self.panels.values() if p.status == PanelStatus.COMPLETED]

    def get_stale_panels(self) -> List[PanelState]:
        return [p for p in self.panels.values() if p.status == PanelStatus.STALE]

    def get_panels_needing_hourly_check(self) -> List[PanelState]:
        now = datetime.now()
        hourly_threshold = now - timedelta(minutes=60)

        panels_needing_check = [
            p
            for p in self.panels.values()
            if p.last_allow_check < hourly_threshold and p.status not in (PanelStatus.COMPLETED, PanelStatus.STALE)
        ]

        if panels_needing_check:
            print(f"\n[PanelTracker] Found {len(panels_needing_check)} panel(s) not checked in past hour:")
            for panel in panels_needing_check:
                mins_since_check = int((now - panel.last_allow_check).total_seconds() / 60)
                print(f"  - {panel.window_title[:60]} (last checked {mins_since_check}min ago)")

        return panels_needing_check

    def mark_panel_allow_checked(self, window_title: str, panel_id: str = "") -> None:
        key = self._generate_panel_key(window_title, panel_id)
        if key in self.panels:
            self.panels[key].last_allow_check = datetime.now()
            self._save_state()

    def print_status_summary(self) -> None:
        if not self.panels:
            print("[PanelTracker] No panels being tracked")
            return

        by_status: Dict[PanelStatus, List[PanelState]] = {status: [] for status in PanelStatus}
        for panel in self.panels.values():
            by_status[panel.status].append(panel)

        print("\n" + "=" * 70)
        print("[PanelTracker] Panel Status Summary")
        print("=" * 70)

        for status in PanelStatus:
            panels = by_status[status]
            if not panels:
                continue

            print(f"\n{status.value.upper()} ({len(panels)}):")
            for p in panels:
                scan_age = datetime.now() - p.last_scanned
                scan_age_str = f"{int(scan_age.total_seconds() / 60)}min since scan"

                secondary_note = ""
                if p.last_response_secondary_categories:
                    secondary_labels = [cat.value for cat in p.last_response_secondary_categories[:2]]
                    secondary_note = f" +{','.join(secondary_labels)}"

                if p.status == PanelStatus.STALE:
                    state_str = " [? STALE - not verified recently]"
                elif p.is_running:
                    state_str = " [■ WORKING]"
                elif p.idle_reason == IdleReason.WAITING_ALLOW:
                    state_str = " [⏸ NEEDS ALLOW]"
                elif p.idle_reason == IdleReason.RATE_LIMITED_BUTTON:
                    state_str = " [⚠ RATE LIMITED - Try Again]"
                elif p.idle_reason == IdleReason.RATE_LIMITED_NO_BUTTON:
                    state_str = " [⚠ RATE LIMITED - Need 'continue']"
                elif p.idle_reason == IdleReason.POSSIBLY_FINISHED:
                    state_str = " [▶ POSSIBLY DONE]"
                elif p.status == PanelStatus.NEEDS_INPUT:
                    state_str = " [⚠ NEEDS INPUT]"
                elif p.status == PanelStatus.ERROR:
                    state_str = " [⚠ ERROR]"
                else:
                    state_str = " [▶ IDLE]"

                state_str += secondary_note
                print(f"  • {p.window_title[:50]}... ({scan_age_str}){state_str}")

        print("=" * 70 + "\n")
