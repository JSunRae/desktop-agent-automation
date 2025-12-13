"""Utility for classifying Copilot panel output into actionable categories."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Sequence


class ResponseCategory(Enum):
    """High-level intent detected in a Copilot panel response."""

    COMPLETED = "completed"
    ASKING_CLARIFICATION = "asking_clarification"
    ERROR = "error"
    WORKING = "working"
    SUGGESTING_NEXT_STEPS = "suggesting_next_steps"


@dataclass(frozen=True)
class ParsedResponse:
    """Result returned by :func:`classify_response`."""

    category: ResponseCategory
    confidence: float
    evidence: List[str]
    secondary_categories: List[ResponseCategory] = field(default_factory=list)


@dataclass(frozen=True)
class _Rule:
    category: ResponseCategory
    patterns: Sequence[str]
    base_confidence: float


_COMPLETED_PATTERNS = (
    r"(?<!not\s)\btask\s+completed\b",
    r"(?<!not\s)\bcompleted\b",
    r"\ball done\b",
    r"\bfinished\b",
    r"\bready for review\b",
    r"\bhand(?:-?off)? complete\b",
    r"\bdeliverable is ready\b",
)

_ERROR_PATTERNS = (
    r"\berror\b",
    r"\bexception\b",
    r"\btraceback\b",
    r"\bfail(?:ed|ure)\b",
    r"\bunable to\b",
    r"\bnot able to\b",
    r"\bunhandled\b",
    r"\bpermission denied\b",
)

_ASKING_PATTERNS = (
    r"\bcan you\b",
    r"\bcould you\b",
    r"\bwould you\b",
    r"\bplease provide\b",
    r"\bplease share\b",
    r"\bi need\b",
    r"\bneed the\b",
    r"\bmissing\s+(?:context|info|information|file|path)\b",
    r"\bwaiting on\b",
    r"\brequires your input\b",
)

_NEXT_STEPS_PATTERNS = (
    r"\bnext steps?\b",
    r"\bfollow[- ]?up\b",
    r"\bfuture work\b",
    r"\brecommend(?:ed)? next\b",
    r"\bplan to\b",
    r"\bfurther improvements\b",
)

_WORKING_PATTERNS = (
    r"\bworking on\b",
    r"\bin progress\b",
    r"\bcurrently\b",
    r"\bprocessing\b",
    r"\bcontinuing\b",
    r"\bongoing\b",
)

_RULES: Sequence[_Rule] = (
    _Rule(ResponseCategory.COMPLETED, _COMPLETED_PATTERNS, 0.95),
    _Rule(ResponseCategory.ERROR, _ERROR_PATTERNS, 0.9),
    _Rule(ResponseCategory.ASKING_CLARIFICATION, _ASKING_PATTERNS, 0.85),
    _Rule(ResponseCategory.SUGGESTING_NEXT_STEPS, _NEXT_STEPS_PATTERNS, 0.8),
    _Rule(ResponseCategory.WORKING, _WORKING_PATTERNS, 0.5),
)


def classify_response(text: str) -> ParsedResponse:
    """Classify panel output text into one of the :class:`ResponseCategory` values."""

    normalized = (text or "").strip()
    if not normalized:
        return ParsedResponse(ResponseCategory.WORKING, 0.05, ["empty_output"])

    lower_text = normalized.lower()
    matched_rules: List[tuple[_Rule, List[str]]] = []

    for rule in _RULES:
        matches = _find_matches(lower_text, rule.patterns)
        if matches:
            matched_rules.append((rule, matches))

    if not matched_rules:
        return ParsedResponse(ResponseCategory.WORKING, 0.2, ["no_rule_matched"])

    primary_rule, primary_matches = matched_rules[0]
    evidence = [f"{primary_rule.category.value}:{pattern}" for pattern in primary_matches]
    secondary_categories: List[ResponseCategory] = []

    for rule, matches in matched_rules[1:]:
        secondary_categories.append(rule.category)
        evidence.extend(f"{rule.category.value}:{pattern}" for pattern in matches)

    confidence = min(1.0, primary_rule.base_confidence + 0.03 * len(primary_matches))
    return ParsedResponse(primary_rule.category, confidence, evidence, secondary_categories)


def category_needs_attention(category: ResponseCategory) -> bool:
    """Return True if the panel likely needs human attention."""

    return category in {
        ResponseCategory.ASKING_CLARIFICATION,
        ResponseCategory.ERROR,
        ResponseCategory.SUGGESTING_NEXT_STEPS,
    }


def _find_matches(text: str, patterns: Iterable[str]) -> List[str]:
    matches: List[str] = []
    for pattern in patterns:
        if re.search(pattern, text):
            matches.append(pattern)
    return matches


__all__ = [
    "ResponseCategory",
    "ParsedResponse",
    "classify_response",
    "category_needs_attention",
]
