"""Panel transcript quality analysis utilities.

This module scores Copilot panel transcripts, classifies completion state,
extracts quality issues, and produces dashboard/reporting artifacts.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Optional, Sequence

from automation.panel_state import (
    PanelQualityAssessment,
    PanelState,
    QualityComponentScores,
    QualityStatus,
    QualityTrendEntry,
)


@dataclass
class QualitySignal:
    """Lightweight reasoning artifact for downstream debugging."""

    name: str
    weight: float
    details: str

    def to_dict(self) -> dict:
        return {"name": self.name, "weight": self.weight, "details": self.details}


class PanelQualityAnalyzer:
    """Rule-based transcript analyzer with lightweight NLP heuristics."""

    INCOMPLETE_PATTERNS: Sequence[str] = (
        r"\bTODO\b",
        r"\bto\s*implement\b",
        r"not\s+implemented",
        r"fixme",
        r"\bpass\b",
        r"\.{3}",
        r"placeholder",
    )
    TEST_FAILURE_PATTERNS: Sequence[str] = (
        r"failed\s+tests?",
        r"\bFAIL(?:ED)?\b",
        r"AssertionError",
        r"Traceback",
        r"error:\s",
        r"E\s+\w+",
    )
    MERGE_CONFLICT_TOKENS: Sequence[str] = ("<<<<<<<", "=======", ">>>>>>>")
    PARTIAL_SOLUTION_PHRASES: Sequence[str] = (
        "partial fix",
        "partial solution",
        "draft impl",
        "stubbed",
        "skeleton",
    )
    CONFUSION_PHRASES: Sequence[str] = (
        "not sure",
        "uncertain",
        "confused",
        "stuck",
        "blocked",
        "cannot proceed",
        "need clarification",
    )
    DOC_PHRASES: Sequence[str] = (
        "readme",
        "documentation",
        "docstring",
        "comment",
        "docs",
        "guide",
    )

    DASHBOARD_LIMIT = 25
    HISTORY_LIMIT = 40

    def __init__(self, report_dir: Optional[Path] = None):
        self.report_dir = report_dir or Path(__file__).parent / "quality_reports"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_panel(self, panel: PanelState, transcript_text: str, prompt_text: Optional[str] = None) -> PanelQualityAssessment:
        assessment, trend_entry = self._analyze_transcript(panel, transcript_text, prompt_text)
        panel.quality_assessment = assessment
        panel.needs_human_review = assessment.needs_human_review
        panel.quality_history = self._append_history(panel.quality_history, trend_entry)
        return assessment

    def panels_needing_review(self, panels: Iterable[PanelState]) -> List[PanelState]:
        result: List[PanelState] = []
        for panel in panels:
            assessment = panel.quality_assessment
            if not assessment:
                continue
            if assessment.needs_human_review or assessment.status in (QualityStatus.NEEDS_REVISION, QualityStatus.BLOCKED):
                result.append(panel)
        return sorted(result, key=lambda p: (p.quality_assessment.score if p.quality_assessment else 1.0))

    def build_dashboard_rows(self, panels: Iterable[PanelState]) -> List[dict]:
        rows: List[dict] = []
        for panel in panels:
            qa = panel.quality_assessment
            if not qa:
                continue
            rows.append(
                {
                    "panel": panel.window_title,
                    "task": panel.assigned_task_name or panel.assigned_task_id,
                    "status": qa.status.value,
                    "score": round(qa.score, 3),
                    "issues": qa.issues[:3],
                    "flags": qa.flags[:3],
                    "needs_review": qa.needs_human_review,
                    "last_updated": qa.last_evaluated.isoformat(),
                }
            )
        rows.sort(key=lambda row: (row["needs_review"], row["score"], row["panel"]))
        return rows[: self.DASHBOARD_LIMIT]

    def build_dashboard_summary(self, panels: Iterable[PanelState]) -> dict:
        panel_list = list(panels)
        rows = self.build_dashboard_rows(panel_list)
        total = len(panel_list)
        needs_review = sum(1 for panel in panel_list if panel.needs_human_review or (panel.quality_assessment and panel.quality_assessment.needs_human_review))
        scores = [panel.quality_assessment.score for panel in panel_list if panel.quality_assessment]
        avg_score = round(mean(scores), 3) if scores else 0.0
        status_counts = Counter(
            panel.quality_assessment.status.value if panel.quality_assessment else QualityStatus.UNKNOWN.value
            for panel in panel_list
        )

        issue_counter: Counter[str] = Counter()
        flag_counter: Counter[str] = Counter()
        for panel in panel_list:
            if panel.quality_assessment:
                issue_counter.update(panel.quality_assessment.issues)
                flag_counter.update(panel.quality_assessment.flags)

        quality_concerns = [issue for issue, _ in issue_counter.most_common(5)]
        confusion_panels = [panel for panel in panel_list if panel.quality_assessment and "agent_confusion" in panel.quality_assessment.flags]

        recent_history = self._collect_history_window(panel_list)
        completion_rate = (
            sum(1 for entry in recent_history if entry.status == QualityStatus.COMPLETED) / len(recent_history)
            if recent_history
            else 0.0
        )
        trend = {
            "weekly_completion_rate": round(completion_rate, 3),
            "history_samples": len(recent_history),
        }

        alerts = self._derive_alerts(avg_score, needs_review, total, confusion_panels, rows)

        return {
            "generated_at": datetime.now().isoformat(),
            "total_panels": total,
            "needs_review": needs_review,
            "average_score": avg_score,
            "status_breakdown": dict(status_counts),
            "quality_alerts": alerts,
            "quality_concerns": quality_concerns,
            "trend": trend,
            "rows": rows,
        }

    def generate_weekly_report(
        self,
        panels: Iterable[PanelState],
        *,
        week_ending: Optional[datetime] = None,
        persist: bool = True,
    ) -> dict:
        week_ending = week_ending or datetime.now()
        window_start = week_ending - timedelta(days=7)
        entries: List[QualityTrendEntry] = []
        for panel in panels:
            for record in panel.quality_history:
                if window_start <= record.timestamp <= week_ending:
                    entries.append(record)

        status_counts = Counter(record.status.value for record in entries)
        scores = [record.score for record in entries]
        avg_score = round(mean(scores), 3) if scores else 0.0

        issue_counter: Counter[str] = Counter()
        flag_counter: Counter[str] = Counter()
        for record in entries:
            issue_counter.update(record.issues)
            flag_counter.update(record.flags)

        top_issues = [name for name, _ in issue_counter.most_common(5)]
        top_flags = [name for name, _ in flag_counter.most_common(5)]

        recommendation_pool: List[str] = []
        if status_counts.get(QualityStatus.NEEDS_REVISION.value, 0) > len(entries) * 0.25:
            recommendation_pool.append("Improve review loop for incomplete implementations.")
        if status_counts.get(QualityStatus.BLOCKED.value, 0) > len(entries) * 0.1:
            recommendation_pool.append("Surface blockers to request details earlier.")
        if any(issue for issue in top_issues if "test" in issue.lower()):
            recommendation_pool.append("Add enforcement for test execution in prompts.")
        if not recommendation_pool:
            recommendation_pool.append("Continue monitoring; no systemic regressions detected.")

        report = {
            "generated_at": datetime.now().isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": week_ending.isoformat(),
            "entry_count": len(entries),
            "status_counts": status_counts,
            "avg_score": avg_score,
            "top_issues": top_issues,
            "top_flags": top_flags,
            "recommendations": recommendation_pool,
        }

        if persist:
            self._persist_report(report, week_ending)

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _analyze_transcript(
        self,
        panel: PanelState,
        transcript_text: str,
        prompt_text: Optional[str] = None,
    ) -> tuple[PanelQualityAssessment, QualityTrendEntry]:
        text = transcript_text or panel.last_output_sample or ""
        if not text and panel.transcript_snapshots:
            previews = [snap.preview for snap in panel.transcript_snapshots if snap.preview]
            text = "\n".join(previews)
        normalized = text.lower()
        prompt_text = prompt_text or panel.assigned_prompt_text or panel.last_seed_prompt_text or ""

        signals: List[QualitySignal] = []
        flags: List[str] = []
        issues: List[str] = []

        incomplete_hits = self._count_patterns(self.INCOMPLETE_PATTERNS, text)
        if incomplete_hits:
            issues.append("Incomplete implementation markers present")
            flags.append("incomplete_implementation")
            signals.append(QualitySignal("incomplete_markers", min(1.0, incomplete_hits / 3), f"{incomplete_hits} markers"))

        placeholder_hits = self._count_patterns(self.PARTIAL_SOLUTION_PHRASES, normalized)
        if placeholder_hits:
            issues.append("Partial or placeholder solution detected")
            flags.append("partial_solution")
            signals.append(QualitySignal("partial_solution", min(1.0, placeholder_hits / 2), f"{placeholder_hits} hints"))

        test_failures = self._count_patterns(self.TEST_FAILURE_PATTERNS, text)
        if test_failures:
            issues.append("Tests failing or errors observed")
            flags.append("test_failures")
            signals.append(QualitySignal("test_failures", min(1.0, test_failures / 2), f"{test_failures} failures"))

        merge_conflicts = sum(token in text for token in self.MERGE_CONFLICT_TOKENS)
        if merge_conflicts:
            issues.append("Merge conflict markers present")
            flags.append("merge_conflict")
            signals.append(QualitySignal("merge_conflict", 1.0, "Conflict markers detected"))

        confusion_hits = self._count_patterns(self.CONFUSION_PHRASES, normalized)
        if confusion_hits:
            flags.append("agent_confusion")
            issues.append("Agent expressed confusion or blocking condition")
            signals.append(QualitySignal("confusion", min(1.0, confusion_hits / 2), f"{confusion_hits} mentions"))

        error_tokens = normalized.count("error") + normalized.count("exception")
        if error_tokens and not test_failures:
            issues.append("Runtime errors referenced")
            flags.append("runtime_errors")
            signals.append(QualitySignal("runtime_errors", min(1.0, error_tokens / 5), f"{error_tokens} mentions"))

        doc_mentions = self._count_patterns(self.DOC_PHRASES, normalized)

        component_scores = QualityComponentScores(
            code_completeness=self._score_code_completeness(incomplete_hits, placeholder_hits, merge_conflicts),
            test_coverage=self._score_test_coverage(test_failures, normalized),
            error_free_execution=self._score_error_free(test_failures + error_tokens),
            documentation=self._score_documentation(doc_mentions),
            prompt_alignment=self._score_alignment(prompt_text, normalized),
        )

        score = self._compute_overall_score(component_scores)
        status = self._classify_status(component_scores, normalized, flags)
        needs_review = self._should_flag_for_review(score, status, panel)

        if self._has_repeated_failures(panel):
            issues.append("Repeated low-quality outputs detected")
            if "repeated_failures" not in flags:
                flags.append("repeated_failures")
            needs_review = True

        if self._detect_degraded_output(panel, score):
            issues.append("Output quality degraded versus previous run")
            if "degraded_output" not in flags:
                flags.append("degraded_output")

        if needs_review and "needs_review" not in flags:
            flags.append("needs_review")

        notes = self._compose_notes(signals)

        assessment = PanelQualityAssessment(
            status=status,
            score=score,
            confidence=self._estimate_confidence(text, issues),
            component_scores=component_scores,
            issues=issues,
            flags=flags,
            notes=notes,
            needs_human_review=needs_review,
            last_evaluated=datetime.now(),
        )

        trend_entry = QualityTrendEntry(
            timestamp=assessment.last_evaluated,
            status=status,
            score=score,
            issues=issues,
            flags=flags,
        )

        return assessment, trend_entry

    def _append_history(self, history: List[QualityTrendEntry], entry: QualityTrendEntry) -> List[QualityTrendEntry]:
        updated = list(history) if history else []
        updated.append(entry)
        return updated[-self.HISTORY_LIMIT :]

    def _derive_alerts(
        self,
        avg_score: float,
        needs_review: int,
        total: int,
        confusion_panels: Sequence[PanelState],
        rows: Sequence[dict],
    ) -> List[str]:
        alerts: List[str] = []
        if total and avg_score < 0.65:
            alerts.append("Average quality score dropped below 0.65")
        threshold = max(3, int(total * 0.3))
        if needs_review > threshold:
            alerts.append(f"{needs_review} panels require human review")
        if confusion_panels:
            alerts.append(f"{len(confusion_panels)} panels show signs of agent confusion")
        low_scores = [row for row in rows if row.get("score", 1.0) < 0.5]
        if low_scores:
            alerts.append(f"{len(low_scores)} panels scoring below 0.50")
        return alerts

    def _collect_history_window(self, panels: Sequence[PanelState]) -> List[QualityTrendEntry]:
        horizon = datetime.now() - timedelta(days=7)
        entries: List[QualityTrendEntry] = []
        for panel in panels:
            for record in panel.quality_history[-10:]:
                if record.timestamp >= horizon:
                    entries.append(record)
        if entries:
            return entries
        fallback: List[QualityTrendEntry] = []
        for panel in panels:
            fallback.extend(panel.quality_history[-5:])
        return fallback

    def _has_repeated_failures(self, panel: PanelState) -> bool:
        recent = panel.quality_history[-3:]
        if len(recent) < 3:
            return False
        return all(entry.status in (QualityStatus.NEEDS_REVISION, QualityStatus.BLOCKED) for entry in recent)

    def _detect_degraded_output(self, panel: PanelState, new_score: float) -> bool:
        if not panel.quality_history:
            return False
        previous = panel.quality_history[-1].score
        return new_score + 0.15 < previous

    # ------------------------------------------------------------------
    # Component scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_patterns(patterns: Sequence[str], text: str) -> int:
        if not text:
            return 0
        total = 0
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            total += len(matches)
        return total

    @staticmethod
    def _score_code_completeness(incomplete_hits: int, placeholder_hits: int, merge_conflicts: int) -> float:
        penalties = 0.2 * incomplete_hits + 0.15 * placeholder_hits + 0.5 * merge_conflicts
        return max(0.0, 1.0 - min(1.0, penalties))

    @staticmethod
    def _score_test_coverage(test_failures: int, normalized_text: str) -> float:
        if test_failures:
            return max(0.0, 0.5 - 0.1 * test_failures)
        if "test" in normalized_text and any(word in normalized_text for word in ("pass", "green", "success")):
            return 1.0
        if "test" in normalized_text:
            return 0.7
        return 0.5

    @staticmethod
    def _score_error_free(error_mentions: int) -> float:
        if error_mentions == 0:
            return 1.0
        return max(0.0, 0.8 - 0.1 * error_mentions)

    def _score_documentation(self, doc_mentions: int) -> float:
        if doc_mentions > 2:
            return 1.0
        if doc_mentions:
            return 0.8
        return 0.45

    @staticmethod
    def _score_alignment(prompt_text: str, normalized_text: str) -> float:
        if not prompt_text:
            return 0.6
        prompt_terms = set(re.findall(r"\b[a-zA-Z0-9_]{4,}\b", prompt_text.lower()))
        if not prompt_terms:
            return 0.6
        hits = sum(1 for term in prompt_terms if term in normalized_text)
        coverage = hits / len(prompt_terms)
        return min(1.0, 0.5 + coverage)

    @staticmethod
    def _compute_overall_score(component_scores: QualityComponentScores) -> float:
        values = [
            component_scores.code_completeness,
            component_scores.test_coverage,
            component_scores.error_free_execution,
            component_scores.documentation,
            component_scores.prompt_alignment,
        ]
        return round(sum(values) / len(values), 3)

    @staticmethod
    def _classify_status(component_scores: QualityComponentScores, normalized_text: str, flags: Sequence[str]) -> QualityStatus:
        if "task completed" in normalized_text or component_scores.code_completeness > 0.9 and component_scores.error_free_execution > 0.9:
            if "test_failures" not in flags and "merge_conflict" not in flags:
                return QualityStatus.COMPLETED
        if "agent_confusion" in flags or "needs_review" in flags:
            return QualityStatus.BLOCKED
        if "incomplete_implementation" in flags or component_scores.code_completeness < 0.6:
            return QualityStatus.NEEDS_REVISION
        if "test_failures" in flags or component_scores.test_coverage < 0.6:
            return QualityStatus.IN_PROGRESS
        return QualityStatus.IN_PROGRESS

    def _should_flag_for_review(self, score: float, status: QualityStatus, panel: PanelState) -> bool:
        if score < 0.5 or status == QualityStatus.BLOCKED:
            return True
        recent = [entry for entry in panel.quality_history[-3:] if entry.status != QualityStatus.UNKNOWN]
        if len(recent) == 3 and all(entry.status != QualityStatus.COMPLETED for entry in recent):
            return True
        return False

    @staticmethod
    def _compose_notes(signals: Sequence[QualitySignal]) -> Optional[str]:
        if not signals:
            return None
        parts = [f"{signal.name}:{signal.details}" for signal in signals]
        return "; ".join(parts)

    @staticmethod
    def _estimate_confidence(text: str, issues: Sequence[str]) -> float:
        length_factor = min(1.0, max(0.2, len(text) / 1000))
        penalty = 0.1 * len(issues)
        return round(max(0.1, length_factor - penalty), 3)

    def _persist_report(self, report: dict, week_ending: datetime) -> None:
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            filename = f"quality_report_{week_ending.strftime('%Y_%m_%d')}.json"
            path = self.report_dir / filename
            with path.open("w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, default=self._json_default)
        except Exception as exc:
            print(f"[PanelQualityAnalyzer] Failed to persist weekly report: {exc}")

    @staticmethod
    def _json_default(value: object):
        if isinstance(value, Counter):
            return dict(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def get_panel_quality_analyzer() -> PanelQualityAnalyzer:
    """Shared analyzer instance."""

    if not hasattr(get_panel_quality_analyzer, "_instance"):
        get_panel_quality_analyzer._instance = PanelQualityAnalyzer()  # type: ignore[attr-defined]
    return get_panel_quality_analyzer._instance  # type: ignore[attr-defined]
