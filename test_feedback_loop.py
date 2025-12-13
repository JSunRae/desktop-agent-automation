#!/usr/bin/env python3
"""
Test script for the feedback loop implementation.

This script tests the feedback loop components:
- Response parsing
- Feedback recording
- Feedback analysis
- Prompt filtering
"""

from automation.response_parser import classify_response, ResponseCategory
from automation.metrics import get_metrics_tracker
from automation.feedback_analyzer import get_feedback_analyzer
from automation.panel_tracker import _compute_prompt_identifier


def test_response_parsing():
    """Test response parsing functionality."""
    print("Testing response parsing...")

    # Test completion
    response = classify_response("Task completed successfully! All requirements implemented.")
    assert response.category == ResponseCategory.COMPLETED
    assert response.confidence > 0.9
    print(f"✓ Completion detected: {response.category.value} ({response.confidence:.2f})")

    # Test error
    response = classify_response("Error: File not found. Unable to proceed.")
    assert response.category == ResponseCategory.ERROR
    print(f"✓ Error detected: {response.category.value} ({response.confidence:.2f})")

    # Test clarification request
    response = classify_response("I need the API key to continue. Can you provide it?")
    assert response.category == ResponseCategory.ASKING_CLARIFICATION
    print(f"✓ Clarification detected: {response.category.value} ({response.confidence:.2f})")


def test_feedback_recording():
    """Test feedback recording in metrics."""
    print("\nTesting feedback recording...")

    tracker = get_metrics_tracker()

    # Record some test feedback
    tracker.record_response_feedback(
        panel_title="Test Panel - test.py",
        response_category=ResponseCategory.COMPLETED,
        response_confidence=0.95,
        response_evidence=["completed", "task completed"],
        response_sample="Task completed successfully!",
        prompt_id="test_prompt_123",
        prompt_preview="Implement user authentication",
        is_sensitive=False,
        processing_time_seconds=45.2,
    )

    tracker.record_response_feedback(
        panel_title="Test Panel - error.py",
        response_category=ResponseCategory.ERROR,
        response_confidence=0.88,
        response_evidence=["error", "exception"],
        response_sample="ValueError: invalid input",
        prompt_id="test_prompt_456",
        prompt_preview="Parse user input data",
        is_sensitive=False,
        processing_time_seconds=12.1,
    )

    # Check metrics
    summary = tracker.get_summary()
    assert summary['total_response_feedback'] >= 2
    print(f"✓ Recorded {summary['total_response_feedback']} feedback entries")

    # Check categories
    categories = summary['response_categories']
    assert 'completed' in categories
    assert 'error' in categories
    print(f"✓ Categories recorded: {list(categories.keys())}")


def test_feedback_analysis():
    """Test feedback analysis functionality."""
    print("\nTesting feedback analysis...")

    analyzer = get_feedback_analyzer()

    # Analyze feedback
    insights = analyzer.analyze_feedback(min_responses=1)

    assert len(insights.prompt_performance) > 0
    print(f"✓ Analyzed {len(insights.prompt_performance)} prompts")

    # Check performance scores
    for perf in insights.prompt_performance:
        print(f"  - Prompt {perf.prompt_id[:8]}: {perf.success_rate:.1%} success rate")

    # Test prompt filtering
    test_prompt = "Implement user authentication system"
    prompt_id = _compute_prompt_identifier(test_prompt)

    should_filter, reason = analyzer.should_filter_prompt(test_prompt, prompt_id)
    print(f"✓ Prompt filtering check: {should_filter} ({reason})")


def test_sensitive_content_detection():
    """Test sensitive content detection."""
    print("\nTesting sensitive content detection...")

    from automation.panel_tracker import PanelTracker

    # Create a mock panel tracker just for testing the method
    tracker = PanelTracker()

    # Test non-sensitive content
    assert not tracker._is_response_sensitive("Task completed successfully!")
    print("✓ Non-sensitive content passed")

    # Test sensitive content
    assert tracker._is_response_sensitive("API key: sk-1234567890abcdef")
    assert tracker._is_response_sensitive("Password: mysecretpassword")
    assert tracker._is_response_sensitive("Email: user@example.com")
    print("✓ Sensitive content detected")


def main():
    """Run all tests."""
    print("Running feedback loop tests...\n")

    try:
        test_response_parsing()
        test_feedback_recording()
        test_feedback_analysis()
        test_sensitive_content_detection()

        print("\n🎉 All tests passed! Feedback loop implementation is working.")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    main()