import unittest

from automation.agent_selection_policy import AdaptiveAgentSelectionPolicy


class _FakeMetricsTracker:
    def __init__(self, usage: dict[str, int]) -> None:
        self._usage = usage.copy()

    def get_summary(self) -> dict[str, dict[str, int]]:  # pragma: no cover - simple stub
        return {"model_usage": self._usage.copy()}


class AgentSelectionPolicyTests(unittest.TestCase):
    def test_normal_mode_prefers_codex_mini_when_grok_saturated(self):
        tracker = _FakeMetricsTracker({"Grok": 10, "Codex Mini": 0, "Codex": 0})
        policy = AdaptiveAgentSelectionPolicy(mode="normal", metrics_tracker=tracker)
        annotated = policy.annotate_prompts(["1. Prompt 1: do the work"])
        self.assertIn("(Codex Mini)", annotated[0])

    def test_maximise_mode_prioritises_codex_even_without_history(self):
        tracker = _FakeMetricsTracker({"Grok": 0, "Codex Mini": 0, "Codex": 0})
        policy = AdaptiveAgentSelectionPolicy(mode="maximise", metrics_tracker=tracker)
        annotated = policy.annotate_prompts(["1. Prompt 1: high value task"])
        self.assertTrue(annotated[0].lower().endswith("(codex):"))

    def test_annotate_replaces_existing_model_labels(self):
        tracker = _FakeMetricsTracker({"Grok": 0, "Codex Mini": 0, "Codex": 0})
        policy = AdaptiveAgentSelectionPolicy(mode="normal", metrics_tracker=tracker)
        prompt = "1. Prompt (Codex Mini): check docs\nDetails follow."
        annotated = policy.annotate_prompts([prompt])
        header = annotated[0].splitlines()[0]
        self.assertTrue(header.endswith("(Grok):"))