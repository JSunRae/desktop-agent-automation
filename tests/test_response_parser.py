"""Tests for the response parser module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.response_parser import (  # noqa: E402
    ResponseCategory,
    category_needs_attention,
    classify_response,
)


class ResponseParserTests(unittest.TestCase):
    def test_classifies_completed_status(self) -> None:
        parsed = classify_response("Task completed successfully and ready for review.")
        self.assertIs(parsed.category, ResponseCategory.COMPLETED)
        self.assertGreaterEqual(parsed.confidence, 0.95)

    def test_detects_clarification_requests(self) -> None:
        parsed = classify_response("I need the file path for the config. Can you provide it?")
        self.assertIs(parsed.category, ResponseCategory.ASKING_CLARIFICATION)
        self.assertTrue(category_needs_attention(parsed.category))

    def test_detects_errors(self) -> None:
        parsed = classify_response("Execution failed with an exception: ValueError: bad input")
        self.assertIs(parsed.category, ResponseCategory.ERROR)
        self.assertGreaterEqual(parsed.confidence, 0.9)

    def test_detects_next_steps_recommendations(self) -> None:
        parsed = classify_response("Next steps: run integration tests, then deploy to staging")
        self.assertIs(parsed.category, ResponseCategory.SUGGESTING_NEXT_STEPS)
        self.assertTrue(category_needs_attention(parsed.category))

    def test_defaults_to_working_when_unclear(self) -> None:
        parsed = classify_response("Continuing to refactor the main module and will report back.")
        self.assertIs(parsed.category, ResponseCategory.WORKING)
        self.assertGreaterEqual(parsed.confidence, 0.5)

    def test_reports_secondary_categories(self) -> None:
        text = "Next steps: run the suite. Also, could you provide the .env file?"
        parsed = classify_response(text)
        self.assertIs(parsed.category, ResponseCategory.ASKING_CLARIFICATION)
        self.assertIn(ResponseCategory.SUGGESTING_NEXT_STEPS, parsed.secondary_categories)


if __name__ == "__main__":
    unittest.main()
