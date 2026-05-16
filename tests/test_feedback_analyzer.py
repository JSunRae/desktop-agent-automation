from __future__ import annotations

import json
from pathlib import Path

from automation.feedback_analyzer import FeedbackAnalyzer, FeedbackInsights


def test_feedback_analyzer_persist_analysis_honors_env_override(monkeypatch, tmp_path: Path) -> None:
    override_path = tmp_path / "cross_repo_todo_cache.json"
    monkeypatch.setenv("CROSS_REPO_TODO_CACHE_PATH", str(override_path))
    analyzer = FeedbackAnalyzer()
    analyzer._analysis_cache = FeedbackInsights(
        prompt_performance=[],
        problematic_patterns=[],
        successful_patterns=[],
        recommended_filters=[],
    )

    persisted = analyzer.persist_analysis()

    assert persisted == override_path
    payload = json.loads(override_path.read_text(encoding="utf-8"))
    assert "prompt_analysis" in payload
