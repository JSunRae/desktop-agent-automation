"""Heuristics for analyzing panel transcript snapshots and latest output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Sequence

from automation.panel_state import (
    PanelQualityAssessment,
    QualityComponentScores,
    QualityStatus,
    QualityTrendEntry,
)


@dataclass
class TranscriptAnalysisResult:
    """Structured analysis for a panel's transcript."""

    assessment: PanelQualityAssessment
    trend_entry: QualityTrendEntry
    issue_tags: List[str]
    summary: str


class TranscriptAnalyzer:
    """Detects risky transcript patterns and computes quality scores."""

    _PATTERNS: Sequence[tuple[str, str, str, float]] = (
        ("todo_marker", "Contains TODO/FIXME markers", r"\b(?:todo|fixme|tbd|xxx)\b", 0.15),
        ("placeholder_code", "Contains placeholder or stub code", r"\b(?:pass|noop|not\s+implemented)\b", 0.2),
        ("test_failure", "Indicates test failures or assertions", r"\b(?:failed|traceback|assertion|E\s+\S)\b", 0.25),
        ("merge_conflict", "Contains merge conflict markers", r"<<<<<<<|=======|>>>>>>>", 0.3),
        (
            "partial_solution",
            "Describes partial or incomplete solution",
            r"partial\s+(?:solution|implementation)|still\s+need|follow[- ]?up",
            0.2,
        ),
        ("error_output", "Shows runtime errors", r"\bexception\b|\bunhandled\b|\bstack trace\b", 0.2),
    )

    _PLACEHOLDER_PHRASES: Sequence[str] = (
        "TODO",
        "FIXME",
        "TBD",
        "not implemented",
        "placeholder",
        "partial implementation",
        "needs tests",
    )

    def analyze(self, *, transcript_texts: Iterable[str], latest_output: str, status_hint: QualityStatus) -> TranscriptAnalysisResult:
        now = datetime.now()
        combined = self._combine_text(transcript_texts, latest_output)
        issue_tags = self._detect_issue_tags(combined)
        severity = sum(weight for _, _, weight in issue_tags)
        score = max(0.0, min(1.0, 1.0 - severity))

        component_scores = QualityComponentScores(
            code_completeness=self._component_score(issue_tags, {"todo_marker", "placeholder_code", "partial_solution", "placeholder_phrase"}),
            test_coverage=self._component_score(issue_tags, {"test_failure"}),
            error_free_execution=self._component_score(issue_tags, {"error_output", "merge_conflict", "test_failure"}),
            documentation=0.8 if combined.count("##") or combined.count("###") else 0.6,
            prompt_alignment=1.0 if score > 0.7 else 0.6,
        )

        derived_status = self._derive_status(issue_tags, status_hint)
        needs_review = derived_status in {QualityStatus.NEEDS_REVISION, QualityStatus.BLOCKED}
        notes = self._build_summary(issue_tags)
        confidence = 0.9 if issue_tags else 0.6

        assessment = PanelQualityAssessment(
            status=derived_status,
            score=score,
            confidence=confidence,
            component_scores=component_scores,
            issues=[tag for tag, _, _ in issue_tags],
            flags=[desc for _, desc, _ in issue_tags],
            notes=notes,
            needs_human_review=needs_review,
            last_evaluated=now,
        )
        trend_entry = QualityTrendEntry(
            timestamp=now,
            status=derived_status,
            score=score,
            issues=[tag for tag, _, _ in issue_tags],
            flags=[desc for _, desc, _ in issue_tags],
        )

        summary = notes or ("Healthy transcript" if score > 0.85 else "Monitoring transcript")
        return TranscriptAnalysisResult(
            assessment=assessment,
            trend_entry=trend_entry,
            issue_tags=[tag for tag, _, _ in issue_tags],
            summary=summary,
        )

    def _combine_text(self, transcript_texts: Iterable[str], latest_output: str) -> str:
        texts = [t for t in transcript_texts if t]
        if latest_output:
            texts.append(latest_output)
        return "\n".join(texts).lower()

    def _detect_issue_tags(self, text: str) -> List[tuple[str, str, float]]:
        issues: List[tuple[str, str, float]] = []
        for tag, description, pattern, penalty in self._PATTERNS:
            if re.search(pattern, text):
                issues.append((tag, description, penalty))
        for phrase in self._PLACEHOLDER_PHRASES:
            if phrase.lower() in text:
                issues.append(("placeholder_phrase", f"Contains '{phrase}'", 0.15))
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: List[tuple[str, str, float]] = []
        for tag, description, penalty in issues:
            if tag in seen:
                continue
            unique.append((tag, description, penalty))
            seen.add(tag)
        return unique

    def _component_score(self, issues: Sequence[tuple[str, str, float]], match_tags: set[str]) -> float:
        if not match_tags:
            return 1.0
        hits = sum(1 for tag, _, _ in issues if tag in match_tags)
        return max(0.2, 1.0 - 0.3 * hits)

    def _derive_status(self, issues: Sequence[tuple[str, str, float]], status_hint: QualityStatus) -> QualityStatus:
        tags = {tag for tag, _, _ in issues}
        if "merge_conflict" in tags or "test_failure" in tags:
            return QualityStatus.BLOCKED
        if tags.intersection({"todo_marker", "placeholder_code", "partial_solution", "placeholder_phrase"}):
            return QualityStatus.NEEDS_REVISION
        if not tags and status_hint == QualityStatus.UNKNOWN:
            return QualityStatus.IN_PROGRESS
        return status_hint if tags else QualityStatus.COMPLETED

    def _build_summary(self, issues: Sequence[tuple[str, str, float]]) -> str:
        if not issues:
            return ""
        descriptions = [desc for _, desc, _ in issues]
        return "; ".join(descriptions[:4])


def analyze_panel_transcripts(transcript_texts: Iterable[str], latest_output: str, *, status_hint: QualityStatus = QualityStatus.UNKNOWN) -> TranscriptAnalysisResult:
    """Convenience wrapper for callers that do not need an analyzer instance."""

    analyzer = TranscriptAnalyzer()
    return analyzer.analyze(transcript_texts=transcript_texts, latest_output=latest_output, status_hint=status_hint)


__all__ = [
    "TranscriptAnalysisResult",
    "TranscriptAnalyzer",
    "analyze_panel_transcripts",
]
