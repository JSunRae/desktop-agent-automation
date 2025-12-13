"""
Feedback analysis and prompt refinement for desktop agent automation.

This module analyzes response feedback to:
- Identify successful vs failed prompt patterns
- Suggest prompt improvements
- Filter out problematic prompts
- Provide insights for prompt generation
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from automation.metrics import get_metrics_tracker
from automation.panel_state import PanelQualityAssessment, PanelState, QualityStatus
from automation.panel_transcript_analysis import TranscriptAnalysisResult
from automation.response_parser import ResponseCategory, classify_response


@dataclass
class PromptPerformance:
    """Performance metrics for a specific prompt."""
    prompt_id: str
    prompt_preview: str
    total_responses: int
    successful_responses: int  # COMPLETED category
    error_responses: int       # ERROR category
    clarification_requests: int # ASKING_CLARIFICATION category
    avg_confidence: float
    avg_processing_time: Optional[float]
    avg_quality_score: Optional[float] = None
    quality_status_breakdown: Dict[str, int] = field(default_factory=dict)
    
    @property
    def success_rate(self) -> float:
        """Success rate (completed responses / total responses)."""
        return self.successful_responses / self.total_responses if self.total_responses > 0 else 0
    
    @property
    def error_rate(self) -> float:
        """Error rate (error responses / total responses)."""
        return self.error_responses / self.total_responses if self.total_responses > 0 else 0


@dataclass
class FeedbackInsights:
    """Analysis insights from response feedback."""
    prompt_performance: List[PromptPerformance]
    problematic_patterns: List[str]
    successful_patterns: List[str]
    recommended_filters: List[str]
    panel_flags: List["PanelTranscriptFlag"] = field(default_factory=list)
    prompt_blocklist: List[str] = field(default_factory=list)
    prompt_whitelist: List[str] = field(default_factory=list)


@dataclass
class PanelTranscriptFlag:
    """Structured record describing a panel that needs review."""

    panel_id: str
    window_title: str
    issues: List[str]
    summary: str
    needs_human_review: bool
    prompt_id: Optional[str]
    prompt_preview: Optional[str]
    timestamp: datetime


class FeedbackAnalyzer:
    """Analyzes response feedback to improve prompt generation."""
    
    def __init__(self):
        self.metrics_tracker = get_metrics_tracker()
        self._pattern_blocklist: Dict[str, int] = {}
        self._pattern_whitelist: Dict[str, int] = {}
        self._transcript_flags: Dict[str, PanelTranscriptFlag] = {}
        self._performance_index: Dict[str, PromptPerformance] = {}
        self._analysis_cache: Optional[FeedbackInsights] = None
        self._cache_timestamp: Optional[datetime] = None
        self.prompt_quality_scores: Dict[str, List[float]] = defaultdict(list)
        self.prompt_quality_statuses: Dict[str, Counter[str]] = defaultdict(Counter)
    
    def analyze_feedback(self, min_responses: int = 3) -> FeedbackInsights:
        """
        Analyze collected feedback to generate insights.
        
        Args:
            min_responses: Minimum responses needed for a prompt to be analyzed
            
        Returns:
            FeedbackInsights with analysis results
        """
        feedback_metrics = self.metrics_tracker.response_feedback_metrics

        prompt_groups: Dict[str, List] = defaultdict(list)
        for metric in feedback_metrics:
            if metric.prompt_id:
                prompt_groups[metric.prompt_id].append(metric)

        prompt_performance: List[PromptPerformance] = []
        for prompt_id, metrics in prompt_groups.items():
            if len(metrics) < min_responses:
                continue

            prompt_preview = metrics[0].prompt_preview or ""
            total_responses = len(metrics)
            successful_responses = sum(1 for m in metrics if m.response_category == ResponseCategory.COMPLETED)
            error_responses = sum(1 for m in metrics if m.response_category == ResponseCategory.ERROR)
            clarification_requests = sum(
                1 for m in metrics if m.response_category == ResponseCategory.ASKING_CLARIFICATION
            )

            avg_confidence = sum(m.response_confidence for m in metrics) / total_responses
            processing_times = [m.processing_time_seconds for m in metrics if m.processing_time_seconds]
            avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else None
            quality_scores = self.prompt_quality_scores.get(prompt_id, [])
            avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else None
            status_counts_counter = self.prompt_quality_statuses.get(prompt_id)
            quality_status_breakdown = dict(status_counts_counter) if status_counts_counter else {}

            performance = PromptPerformance(
                prompt_id=prompt_id,
                prompt_preview=prompt_preview,
                total_responses=total_responses,
                successful_responses=successful_responses,
                error_responses=error_responses,
                clarification_requests=clarification_requests,
                avg_confidence=avg_confidence,
                avg_processing_time=avg_processing_time,
                avg_quality_score=avg_quality_score,
                quality_status_breakdown=quality_status_breakdown,
            )
            prompt_performance.append(performance)

        prompt_performance.sort(key=lambda p: p.success_rate, reverse=True)
        self._performance_index = {perf.prompt_id: perf for perf in prompt_performance}

        problematic_patterns = self._identify_problematic_patterns(feedback_metrics)
        successful_patterns = self._identify_successful_patterns(feedback_metrics)
        recommended_filters = self._generate_recommended_filters(prompt_performance)
        blocklisted_terms = self._refresh_blocklist(prompt_performance)
        allowlisted_terms = self._refresh_whitelist(prompt_performance)
        panel_flags = self._collect_panel_flags()

        insights = FeedbackInsights(
            prompt_performance=prompt_performance,
            problematic_patterns=problematic_patterns,
            successful_patterns=successful_patterns,
            recommended_filters=recommended_filters,
            panel_flags=panel_flags,
            prompt_blocklist=blocklisted_terms,
            prompt_whitelist=allowlisted_terms,
        )

        self._analysis_cache = insights
        self._cache_timestamp = datetime.now(timezone.utc)
        try:
            self.persist_analysis()
        except Exception as exc:
            print(f"[FeedbackAnalyzer] Warning: could not persist analysis: {exc}")
        return insights
    
    def _identify_problematic_patterns(self, feedback_metrics) -> List[str]:
        """Identify patterns in prompts that lead to errors or clarification requests."""
        patterns = []
        
        # Group error/clarification responses by prompt preview
        error_previews = [
            m.prompt_preview for m in feedback_metrics
            if m.prompt_preview and m.response_category in (ResponseCategory.ERROR, ResponseCategory.ASKING_CLARIFICATION)
        ]
        
        if len(error_previews) < 5:
            return patterns
            
        # Simple pattern extraction (could be enhanced with NLP)
        common_words = self._extract_common_words(error_previews)
        patterns.extend([f"Contains word: '{word}'" for word in common_words[:5]])
        signature_counts: Dict[str, int] = defaultdict(int)
        for metric in feedback_metrics:
            if metric.response_sample:
                parsed = classify_response(metric.response_sample)
                if parsed.category in (ResponseCategory.ERROR, ResponseCategory.ASKING_CLARIFICATION):
                    for evidence in parsed.evidence:
                        signature_counts[evidence] += 1
        if signature_counts:
            ranked = sorted(signature_counts.items(), key=lambda item: item[1], reverse=True)
            patterns.extend([f"Response signature: {sig}" for sig, _ in ranked[:5]])
        
        return patterns
    
    def _identify_successful_patterns(self, feedback_metrics) -> List[str]:
        """Identify patterns in prompts that lead to successful completions."""
        patterns = []
        
        # Group successful responses by prompt preview
        success_previews = [
            m.prompt_preview for m in feedback_metrics
            if m.prompt_preview and m.response_category == ResponseCategory.COMPLETED
        ]
        
        if len(success_previews) < 5:
            return patterns
            
        # Simple pattern extraction
        common_words = self._extract_common_words(success_previews)
        patterns.extend([f"Contains word: '{word}'" for word in common_words[:5]])
        signature_counts: Dict[str, int] = defaultdict(int)
        for metric in feedback_metrics:
            if metric.response_sample:
                parsed = classify_response(metric.response_sample)
                if parsed.category == ResponseCategory.COMPLETED:
                    for evidence in parsed.evidence:
                        signature_counts[evidence] += 1
        if signature_counts:
            ranked = sorted(signature_counts.items(), key=lambda item: item[1], reverse=True)
            patterns.extend([f"Completion signature: {sig}" for sig, _ in ranked[:5]])
        
        return patterns
    
    def _extract_common_words(self, texts: List[str]) -> List[str]:
        """Extract most common meaningful words from a list of texts."""
        word_counts = defaultdict(int)
        
        for text in texts:
            if not text:
                continue
            # Simple tokenization (remove punctuation, split on spaces)
            words = re.findall(r'\b\w+\b', text.lower())
            # Filter out common stop words
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those'}
            words = [w for w in words if len(w) > 3 and w not in stop_words]
            
            for word in words:
                word_counts[word] += 1
        
        # Return top words by frequency
        return sorted(word_counts.keys(), key=lambda w: word_counts[w], reverse=True)
    
    def _generate_recommended_filters(self, prompt_performance: List[PromptPerformance]) -> List[str]:
        """Generate recommended filters based on prompt performance."""
        filters = []
        
        # Filter out prompts with low success rates
        low_success_prompts = [p for p in prompt_performance if p.success_rate < 0.3 and p.total_responses >= 5]
        if low_success_prompts:
            filters.append(f"Avoid prompts similar to: {low_success_prompts[0].prompt_preview[:50]}...")
        
        # Filter out prompts with high error rates
        high_error_prompts = [p for p in prompt_performance if p.error_rate > 0.5 and p.total_responses >= 5]
        if high_error_prompts:
            filters.append(f"Avoid prompts with high error rates like: {high_error_prompts[0].prompt_preview[:50]}...")
        
        return filters

    def _refresh_blocklist(self, prompt_performance: Iterable[PromptPerformance]) -> List[str]:
        for perf in prompt_performance:
            if perf.total_responses < 3:
                continue
            clar_rate = perf.clarification_requests / perf.total_responses
            if perf.error_rate >= 0.4 or clar_rate >= 0.35:
                for keyword in self._extract_keywords(perf.prompt_preview):
                    if not keyword:
                        continue
                    self._pattern_blocklist[keyword] = self._pattern_blocklist.get(keyword, 0) + 1
        return [term for term, _ in self._sorted_terms(self._pattern_blocklist)]

    def _refresh_whitelist(self, prompt_performance: Iterable[PromptPerformance]) -> List[str]:
        for perf in prompt_performance:
            if perf.total_responses < 3:
                continue
            if perf.success_rate >= 0.65 and perf.error_rate <= 0.15:
                for keyword in self._extract_keywords(perf.prompt_preview):
                    if not keyword:
                        continue
                    self._pattern_whitelist[keyword] = self._pattern_whitelist.get(keyword, 0) + 1
        return [term for term, _ in self._sorted_terms(self._pattern_whitelist)]

    def _collect_panel_flags(self) -> List[PanelTranscriptFlag]:
        flags = list(self._transcript_flags.values())
        flags.sort(key=lambda flag: flag.timestamp, reverse=True)
        return flags

    def _sorted_terms(self, term_counts: Dict[str, int], limit: int = 10) -> List[Tuple[str, int]]:
        return sorted(term_counts.items(), key=lambda item: item[1], reverse=True)[:limit]

    def _extract_keywords(self, prompt_text: str) -> List[str]:
        if not prompt_text:
            return []
        words = self._extract_common_words([prompt_text])
        return words[:3]

    def _ensure_analysis_cache(self) -> FeedbackInsights:
        if self._analysis_cache is None:
            return self.analyze_feedback()
        if not self._cache_timestamp:
            return self.analyze_feedback()
        age = datetime.now(timezone.utc) - self._cache_timestamp
        if age.total_seconds() > 300:
            return self.analyze_feedback()
        return self._analysis_cache
    
    def get_prompt_success_score(self, prompt_id: str) -> Optional[float]:
        """
        Get success score for a specific prompt.
        
        Returns success rate (0.0-1.0) or None if insufficient data.
        """
        self._ensure_analysis_cache()
        performance = self._performance_index.get(prompt_id)
        if not performance:
            return None
        if performance.total_responses < 3:
            return None
        return performance.success_rate
    
    def should_filter_prompt(self, prompt_text: str, prompt_id: str) -> Tuple[bool, str]:
        """
        Determine if a prompt should be filtered out based on feedback.
        
        Returns (should_filter, reason)
        """
        insights = self._ensure_analysis_cache()

        lowered = (prompt_text or "").lower()
        for pattern in insights.prompt_blocklist:
            if pattern and pattern in lowered:
                return True, f"Prompt contains blocklisted pattern '{pattern}'"
        success_score = self.get_prompt_success_score(prompt_id)
        if success_score is not None and success_score < 0.2:
            total = len([m for m in self.metrics_tracker.response_feedback_metrics if m.prompt_id == prompt_id])
            return True, f"Low success rate ({success_score:.1%}) based on {total} responses"

        return False, ""

    def record_quality_assessment(
        self,
        panel: PanelState,
        assessment: Optional[PanelQualityAssessment] = None,
    ) -> None:
        """Capture panel-level quality scores for prompt insights."""

        assessment = assessment or panel.quality_assessment
        prompt_id = panel.assigned_prompt_id
        if not prompt_id or assessment is None:
            return

        scores = self.prompt_quality_scores[prompt_id]
        scores.append(assessment.score)
        if len(scores) > 30:
            self.prompt_quality_scores[prompt_id] = scores[-30:]

        status_counter = self.prompt_quality_statuses[prompt_id]
        status_counter[assessment.status.value] += 1

        panel_key = panel.panel_id or panel.window_title
        if assessment.needs_human_review:
            flag = PanelTranscriptFlag(
                panel_id=panel.panel_id or "unknown-panel",
                window_title=panel.window_title,
                issues=assessment.issues or assessment.flags,
                summary=assessment.notes or "Quality review required",
                needs_human_review=True,
                prompt_id=prompt_id,
                prompt_preview=panel.assigned_prompt_text,
                timestamp=assessment.last_evaluated,
            )
            self._transcript_flags[panel_key] = flag
        else:
            self._transcript_flags.pop(panel_key, None)

    def persist_analysis(self, cache_path: Optional[Path] = None) -> Path:
        insights = self._analysis_cache or self.analyze_feedback()
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "blocklist": insights.prompt_blocklist,
            "whitelist": insights.prompt_whitelist,
            "panel_flags": [self._flag_to_dict(flag) for flag in insights.panel_flags[:20]],
            "prompt_performance": [
                {
                    "prompt_id": perf.prompt_id,
                    "success_rate": perf.success_rate,
                    "error_rate": perf.error_rate,
                    "total_responses": perf.total_responses,
                    "clarification_requests": perf.clarification_requests,
                    "prompt_preview": perf.prompt_preview,
                }
                for perf in insights.prompt_performance[:50]
            ],
        }

        path = Path(cache_path) if cache_path else Path(__file__).parent / "cross_repo_todo_cache.json"
        try:
            raw = path.read_text(encoding="utf-8")
            cache = json.loads(raw)
        except FileNotFoundError:
            cache = {"version": 1, "repos": []}
        except json.JSONDecodeError:
            cache = {"version": 1, "repos": []}

        cache["prompt_analysis"] = payload
        path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

        try:
            from automation.prompt_dashboards import render_prompt_dashboard

            render_prompt_dashboard()
        except Exception as dashboard_exc:
            print(f"[FeedbackAnalyzer] Warning: dashboard render failed: {dashboard_exc}")

        return path

    def get_guidance(self) -> FeedbackInsights:
        """Return the freshest adaptive guidance snapshot."""
        return self._ensure_analysis_cache()

    def record_transcript_analysis(self, panel: PanelState, analysis: TranscriptAnalysisResult) -> None:
        panel_key = panel.panel_id or panel.window_title
        if not panel_key:
            return

        flag = PanelTranscriptFlag(
            panel_id=panel_key,
            window_title=panel.window_title,
            issues=list(analysis.issue_tags),
            summary=analysis.summary,
            needs_human_review=analysis.assessment.needs_human_review,
            prompt_id=panel.assigned_prompt_id,
            prompt_preview=panel.assigned_prompt_text,
            timestamp=analysis.assessment.last_evaluated,
        )

        if flag.issues or flag.needs_human_review:
            self._transcript_flags[panel_key] = flag
        else:
            self._transcript_flags.pop(panel_key, None)

        for issue in flag.issues:
            token = f"transcript:{issue}"
            self._pattern_blocklist[token] = self._pattern_blocklist.get(token, 0) + 1

    def _flag_to_dict(self, flag: PanelTranscriptFlag) -> Dict[str, Any]:
        return {
            "panel_id": flag.panel_id,
            "window_title": flag.window_title,
            "issues": flag.issues,
            "summary": flag.summary,
            "needs_human_review": flag.needs_human_review,
            "prompt_id": flag.prompt_id,
            "prompt_preview": flag.prompt_preview,
            "timestamp": flag.timestamp.isoformat(),
        }


def get_feedback_analyzer() -> FeedbackAnalyzer:
    """Get the global feedback analyzer instance."""
    if not hasattr(get_feedback_analyzer, '_instance'):
        get_feedback_analyzer._instance = FeedbackAnalyzer()
    return get_feedback_analyzer._instance
