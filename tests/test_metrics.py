"""
Test metrics tracking functionality.
"""
import datetime
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from automation.metrics import MetricsTracker, PromptMetric, ModelSelectionMetric, AssignmentMetric  # noqa: E402


def test_metrics_loads_once_per_init():
    """Regression: __init__ should call _load_metrics exactly once."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "test_metrics.json"
        with patch.object(MetricsTracker, "_load_metrics", autospec=True, wraps=MetricsTracker._load_metrics) as spy:
            MetricsTracker(metrics_path)
            assert spy.call_count == 1


def test_metrics_persistence():
    """Test that metrics are saved and loaded correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "test_metrics.json"
        
        # Create tracker and record some metrics
        tracker = MetricsTracker(metrics_path)
        
        tracker.record_prompt_seeding(
            panel_title="Test Panel 1 - my-repo - Visual Studio Code",
            prompt_index=0,
            prompt_text="Prompt 1 (Codex Max): Do something amazing",
            model_requested="GPT-5.1-Codex-Max (Preview)",
            success=True,
        )
        
        tracker.record_prompt_seeding(
            panel_title="Test Panel 2 - my-repo - Visual Studio Code",
            prompt_index=1,
            prompt_text="Prompt 2 (Codex): Do something good",
            model_requested="GPT-5.1 Codex",
            success=True,
        )
        
        tracker.record_model_selection(
            panel_title="Test Panel 1 - my-repo - Visual Studio Code",
            model_label="GPT-5.1-Codex-Max (Preview)",
            success=True,
        )
        
        # Verify metrics were saved
        assert metrics_path.exists(), "Metrics file should exist"
        
        # Load metrics in new tracker
        tracker2 = MetricsTracker(metrics_path)
        
        assert len(tracker2.prompt_metrics) == 2, "Should have 2 prompt metrics"
        assert len(tracker2.model_metrics) == 1, "Should have 1 model metric"
        
        # Verify content
        assert tracker2.prompt_metrics[0].prompt_index == 0
        assert tracker2.prompt_metrics[1].prompt_index == 1
        assert "Codex Max" in tracker2.prompt_metrics[0].prompt_preview
        
        print("✓ Metrics persistence test passed")


def test_metrics_summary():
    """Test metrics summary generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "test_metrics.json"
        tracker = MetricsTracker(metrics_path)
        
        # Record various metrics
        for i in range(3):
            tracker.record_prompt_seeding(
                panel_title=f"Panel {i}",
                prompt_index=i % 2,  # Alternating indices
                prompt_text=f"Test prompt {i}",
                model_requested="Codex" if i % 2 == 0 else "Grok",
                success=i < 2,  # First 2 succeed, last fails
            )
        
        summary = tracker.get_summary()
        
        assert summary["total_prompts_seeded"] == 3
        assert summary["successful_prompts"] == 2
        assert summary["failed_prompts"] == 1
        assert summary["success_rate"] == 2/3
        
        # Check model usage
        assert summary["model_usage"]["Codex"] == 2
        assert summary["model_usage"]["Grok"] == 1
        
        # Check prompt distribution
        assert summary["prompt_index_usage"][0] == 2
        assert summary["prompt_index_usage"][1] == 1
        
        print("✓ Metrics summary test passed")


def test_metrics_serialization():
    """Test metric object serialization."""
    now = datetime.datetime.now()
    
    # Test PromptMetric
    metric = PromptMetric(
        timestamp=now,
        panel_title="Test Panel",
        prompt_index=5,
        prompt_preview="Test preview",
        model_requested="Codex",
        success=True,
        error_message=None,
    )
    
    data = metric.to_dict()
    metric2 = PromptMetric.from_dict(data)
    
    assert metric2.panel_title == "Test Panel"
    assert metric2.prompt_index == 5
    assert metric2.model_requested == "Codex"
    assert metric2.success is True
    
    # Test ModelSelectionMetric
    model_metric = ModelSelectionMetric(
        timestamp=now,
        panel_title="Test Panel",
        model_label="GPT-5.1 Codex",
        success=True,
    )
    
    data = model_metric.to_dict()
    model_metric2 = ModelSelectionMetric.from_dict(data)
    
    assert model_metric2.panel_title == "Test Panel"
    assert model_metric2.model_label == "GPT-5.1 Codex"
    
    # Test AssignmentMetric
    assignment_metric = AssignmentMetric(
        timestamp=now,
        prompt_id="test123",
        panel_id="panel123",
        panel_title="Test Panel",
        repo="test-repo",
        outcome="success",
    )
    
    data = assignment_metric.to_dict()
    assignment_metric2 = AssignmentMetric.from_dict(data)
    
    assert assignment_metric2.prompt_id == "test123"
    assert assignment_metric2.panel_id == "panel123"
    assert assignment_metric2.repo == "test-repo"
    assert assignment_metric2.outcome == "success"
    
    print("✓ Metrics serialization test passed")


def test_assignment_tracking():
    """Test assignment tracking functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "test_metrics.json"
        tracker = MetricsTracker(metrics_path)
        
        # Record some assignments
        tracker.record_assignment(
            prompt_id="abc123",
            panel_id="panel1",
            panel_title="Test Panel 1 - my-repo - Visual Studio Code",
            repo="my-repo",
            outcome="success"
        )
        
        tracker.record_assignment(
            prompt_id="def456",
            panel_id="panel2",
            panel_title="Test Panel 2 - other-repo - Visual Studio Code",
            repo="other-repo",
            outcome="failure"
        )
        
        tracker.record_assignment(
            prompt_id="abc123",
            panel_id="panel3",
            panel_title="Test Panel 3 - my-repo - Visual Studio Code",
            repo="my-repo",
            outcome=None  # Pending
        )
        
        # Check in-memory
        assert len(tracker.assignment_metrics) == 3
        
        # Check query functions
        panel_assignments = tracker.get_assignments_by_panel(panel_id="panel1")
        assert len(panel_assignments) == 1
        assert panel_assignments[0].prompt_id == "abc123"
        
        prompt_assignments = tracker.get_assignments_by_prompt("abc123")
        assert len(prompt_assignments) == 2
        
        # Check summary
        summary = tracker.get_summary()
        assert summary["total_assignments"] == 3
        assert summary["assignments_by_repo"]["my-repo"] == 2
        assert summary["assignments_by_repo"]["other-repo"] == 1
        assert summary["assignment_outcomes"]["success"] == 1
        assert summary["assignment_outcomes"]["failure"] == 1
        
        # Check persistence (JSONL file)
        assignment_file = Path(tmpdir) / "assignment_metrics.jsonl"
        assert assignment_file.exists()
        
        with assignment_file.open("r") as f:
            lines = f.readlines()
            assert len(lines) == 3  # Should have 3 JSON lines

        # Loading should not duplicate entries.
        tracker2 = MetricsTracker(metrics_path)
        assert len(tracker2.assignment_metrics) == 3
        tracker2._load_metrics()
        assert len(tracker2.assignment_metrics) == 3
        unique_keys = {(m.prompt_id, m.panel_id, m.panel_title, m.repo, m.outcome) for m in tracker2.assignment_metrics}
        assert len(unique_keys) == 3
        
        print("✓ Assignment tracking test passed")


def test_metrics_tracker_honors_env_overrides(monkeypatch):
    """MetricsTracker should respect env overrides when no path is passed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "env_metrics.json"
        assignment_path = Path(tmpdir) / "env_assignments.jsonl"
        monkeypatch.setenv("AUTOMATION_METRICS_PATH", str(metrics_path))
        monkeypatch.setenv("AUTOMATION_ASSIGNMENT_METRICS_PATH", str(assignment_path))

        tracker = MetricsTracker()

        assert tracker.metrics_path == metrics_path
        assert tracker.assignment_metrics_path == assignment_path


if __name__ == "__main__":
    test_metrics_persistence()
    test_metrics_summary()
    test_metrics_serialization()
    test_assignment_tracking()
    print("\n✅ All metrics tests passed!")
