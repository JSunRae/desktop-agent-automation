from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Optional, Sequence

from automation.metrics import MetricsTracker, get_metrics_tracker


MODEL_NAMES = ("Grok", "Codex Mini", "Codex")


class AgentSelectionMode(Enum):
    """Available agent selection modes for adaptive policy."""

    NORMAL = "normal"
    MAXIMISE = "maximise"

    @classmethod
    def from_value(cls, value: Optional[str | "AgentSelectionMode"]) -> "AgentSelectionMode":
        """Normalize a string or enum into an AgentSelectionMode."""
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.NORMAL
        normalized = value.strip().lower()
        if normalized == "maximize":
            normalized = cls.MAXIMISE.value
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown agent selection mode: {value!r}")


class AdaptiveAgentSelectionPolicy:
    """Adaptive policy that recommends Grok/Codex Mini/Codex per usage stats."""

    _MODEL_LABEL_RE = re.compile(
        r"\s*\((?:grok|codex(?:[-\s](?:mini|max))?)\)",
        flags=re.IGNORECASE,
    )

    _TARGET_RATIOS: Dict[AgentSelectionMode, Dict[str, float]] = {
        AgentSelectionMode.NORMAL: {"Grok": 0.55, "Codex Mini": 0.3, "Codex": 0.15},
        AgentSelectionMode.MAXIMISE: {"Grok": 0.1, "Codex Mini": 0.25, "Codex": 0.65},
    }

    def __init__(
        self,
        *,
        mode: Optional[str | AgentSelectionMode] = None,
        metrics_tracker: Optional[MetricsTracker] = None,
    ) -> None:
        self._mode = AgentSelectionMode.from_value(mode)
        self._tracker = metrics_tracker or get_metrics_tracker()
        self._usage_counts: Dict[str, float] = self._load_usage()

    def annotate_prompts(self, prompts: Sequence[str]) -> List[str]:
        """Return a list of prompts with headers tagged with the selected model."""
        annotated: List[str] = []
        for prompt in prompts:
            model = self._pick_model()
            annotated.append(self._tag_prompt(prompt, model))
        return annotated

    def _load_usage(self) -> Dict[str, float]:
        summary = self._tracker.get_summary()
        recorded = summary.get("model_usage", {})
        return {model: float(recorded.get(model, 0)) for model in MODEL_NAMES}

    def _pick_model(self) -> str:
        target = self._TARGET_RATIOS[self._mode]
        total = sum(self._usage_counts.values()) or 1.0
        deficits = {
            model: target[model] - (self._usage_counts.get(model, 0) / total)
            for model in MODEL_NAMES
        }
        preferred = max(MODEL_NAMES, key=lambda m: (deficits[m], -self._usage_counts.get(m, 0)))
        if deficits[preferred] < 0:
            for fallback in self._fallback_order():
                if deficits[fallback] >= 0:
                    preferred = fallback
                    break
            else:
                preferred = self._fallback_order()[0]
        self._usage_counts[preferred] += 1
        return preferred

    def _fallback_order(self) -> List[str]:
        if self._mode == AgentSelectionMode.MAXIMISE:
            return ["Codex", "Codex Mini", "Grok"]
        return ["Grok", "Codex Mini", "Codex"]

    def _tag_prompt(self, prompt: str, model: str) -> str:
        if not prompt:
            return prompt
        lines = prompt.splitlines()
        header = lines[0]
        header = self._MODEL_LABEL_RE.sub("", header, count=1)
        header = header.rstrip(":").rstrip()
        header = f"{header} ({model}):"
        lines[0] = header
        return "\n".join(lines)