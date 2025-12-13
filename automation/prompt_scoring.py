"""Prompt quality scoring utilities for adaptive assignment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from automation.feedback_analyzer import get_feedback_analyzer


@dataclass
class PromptScore:
    """Breakdown of a prompt's quality assessment."""

    clarity: float
    specificity: float
    actionability: float
    dependency_completeness: float
    historical_success: float
    total: float
    notes: List[str]


class PromptScorer:
    """Scores prompts using structural heuristics and feedback metrics."""

    _ACTION_VERBS = re.compile(r"\b(implement|fix|add|refactor|create|write|document|test|investigate|optimize)\b", re.IGNORECASE)
    _FILE_PATH = re.compile(r"[A-Za-z0-9_./\\]+\.(?:py|ts|tsx|js|md|rst|yaml|yml|json|toml)")
    _FUNCTION_NAME = re.compile(r"\b(?:def|class|function)\s+[A-Za-z0-9_]+", re.IGNORECASE)
    _DEPENDENCY_HINT = re.compile(r"\b(dependenc|requires|needs|context|prerequisite|inputs?)\b", re.IGNORECASE)

    def __init__(self) -> None:
        self._analyzer = get_feedback_analyzer()

    def score_prompt(self, prompt_text: str, prompt_id: Optional[str] = None) -> PromptScore:
        words = self._tokenize(prompt_text)
        sentences = self._split_sentences(prompt_text)

        clarity = self._score_clarity(len(words), len(sentences))
        specificity = self._score_specificity(prompt_text)
        actionability = self._score_actionability(prompt_text)
        dependency = self._score_dependency(prompt_text)
        historical = self._score_historical(prompt_id)

        total = self._combine_scores([
            (clarity, 0.2),
            (specificity, 0.2),
            (actionability, 0.2),
            (dependency, 0.15),
            (historical, 0.25),
        ])

        notes = self._build_notes(prompt_text, clarity, specificity, actionability, dependency)
        return PromptScore(
            clarity=clarity,
            specificity=specificity,
            actionability=actionability,
            dependency_completeness=dependency,
            historical_success=historical,
            total=total,
            notes=notes,
        )

    def rank_prompts(self, prompts: Sequence[Tuple[str, str]]) -> List[Tuple[str, PromptScore]]:
        """Rank prompts using their prompt_id and text."""

        scored = [(prompt_id, self.score_prompt(text, prompt_id)) for prompt_id, text in prompts]
        return sorted(scored, key=lambda item: item[1].total, reverse=True)

    def _tokenize(self, prompt_text: str) -> List[str]:
        return re.findall(r"\b\w+\b", prompt_text)

    def _split_sentences(self, prompt_text: str) -> List[str]:
        return [seg.strip() for seg in re.split(r"[.!?]", prompt_text) if seg.strip()]

    def _score_clarity(self, word_count: int, sentence_count: int) -> float:
        if word_count == 0:
            return 0.0
        ideal_low, ideal_high = 60, 250
        within_range = max(0.0, min(1.0, (word_count - ideal_low) / (ideal_high - ideal_low)))
        sentence_bonus = min(1.0, sentence_count / 6) if sentence_count else 0.3
        return max(0.1, (within_range * 0.7) + (sentence_bonus * 0.3))

    def _score_specificity(self, prompt_text: str) -> float:
        matches = bool(self._FILE_PATH.search(prompt_text)) or bool(self._FUNCTION_NAME.search(prompt_text))
        numbers = len(re.findall(r"\b\d+\b", prompt_text))
        return min(1.0, 0.5 + (0.3 if matches else 0.0) + min(numbers, 3) * 0.05)

    def _score_actionability(self, prompt_text: str) -> float:
        verbs = len(self._ACTION_VERBS.findall(prompt_text))
        has_list = "- " in prompt_text or "1." in prompt_text or "* " in prompt_text
        base = min(1.0, 0.4 + verbs * 0.08)
        if has_list:
            base += 0.2
        return min(1.0, base)

    def _score_dependency(self, prompt_text: str) -> float:
        dependency_mentions = len(self._DEPENDENCY_HINT.findall(prompt_text))
        context_sections = prompt_text.lower().count("context")
        return min(1.0, 0.4 + 0.15 * dependency_mentions + 0.1 * context_sections)

    def _score_historical(self, prompt_id: Optional[str]) -> float:
        if not prompt_id:
            return 0.5
        score = self._analyzer.get_prompt_success_score(prompt_id)
        if score is None:
            return 0.5
        return max(0.0, min(1.0, score))

    def _combine_scores(self, components: Iterable[Tuple[float, float]]) -> float:
        total_weight = sum(weight for _, weight in components)
        weighted = sum(score * weight for score, weight in components)
        return weighted / total_weight if total_weight else 0.0

    def _build_notes(
        self,
        prompt_text: str,
        clarity: float,
        specificity: float,
        actionability: float,
        dependency: float,
    ) -> List[str]:
        notes: List[str] = []
        if clarity < 0.5:
            notes.append("Clarify goals with more detail")
        if specificity < 0.5:
            notes.append("Reference files or functions explicitly")
        if actionability < 0.5:
            notes.append("Add explicit deliverables or action verbs")
        if dependency < 0.5:
            notes.append("List required context or dependencies")
        if "TODO" in prompt_text.upper():
            notes.append("Avoid embedding TODO markers in prompts")
        return notes


__all__ = ["PromptScore", "PromptScorer"]
