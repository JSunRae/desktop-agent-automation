"""Unit tests for scripts.verify_pricing enhancements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import verify_pricing as pricing


def _record(model: str, *, input_rate: float, output_rate: float, vision_rate: float | None = None) -> pricing.PricingRecord:
    return pricing.PricingRecord(model=model, input=input_rate, output=output_rate, vision=vision_rate)


@pytest.fixture
def sample_previous_report() -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "pricing" / "previous_report.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_compare_pricing_detects_increases_and_decreases() -> None:
    current = {
        "gpt-4o": _record("gpt-4o", input_rate=0.001, output_rate=0.002),
        "gpt-4o-mini": _record("gpt-4o-mini", input_rate=0.0005, output_rate=0.0009),
        "gpt-4-turbo": _record("gpt-4-turbo", input_rate=0.002, output_rate=0.003),
    }
    remote = {
        "gpt-4o": _record("gpt-4o", input_rate=0.0015, output_rate=0.0015, vision_rate=0.02),
        "gpt-4-turbo": _record("gpt-4-turbo", input_rate=0.002, output_rate=0.003),
        "gpt-5-mini": _record("gpt-5-mini", input_rate=0.0002, output_rate=0.0004),
    }

    comparison = pricing.compare_pricing(current, remote, tolerance=0.01)

    assert any(change for change in comparison["increased"] if change["model"] == "gpt-4o" and change["rate_type"] == "input")
    assert any(change for change in comparison["decreased"] if change["model"] == "gpt-4o" and change["rate_type"] == "output")
    assert any(change for change in comparison["increased"] if change["rate_type"] == "vision")
    assert "gpt-5-mini" in comparison["new_models"]
    assert "gpt-4o-mini" in comparison["deprecated"]
    assert "gpt-4-turbo" in comparison["unchanged"]


def test_generate_reports(tmp_path: Path) -> None:
    payload = {
        "check_date": "2025-12-13T00:00:00+00:00",
        "checker_version": pricing.CHECKER_VERSION,
        "api_source": "test",
        "comparison": {
            "unchanged_count": 1,
            "increased_count": 1,
            "decreased_count": 0,
            "new_models_count": 1,
            "deprecated_count": 0,
        },
        "changes": {
            "unchanged": ["gpt-4-turbo"],
            "increased": [
                {
                    "model": "gpt-4o",
                    "rate_type": "input",
                    "old_price": 0.001,
                    "new_price": 0.0012,
                    "change_pct": 20.0,
                    "change_per_1m_tokens": 0.2,
                    "delta": 0.0002,
                }
            ],
            "decreased": [],
            "new_models": ["gpt-5-mini"],
            "deprecated": [],
        },
        "full_pricing": {
            "current_code": {"gpt-4o": {"input": 0.001, "output": 0.002, "vision": None}},
            "api_latest": {"gpt-4o": {"input": 0.0012, "output": 0.002, "vision": None}},
        },
        "recommendations": ["Update automation/cost_tracker.py for gpt-4o input rate ($0.0010 -> $0.0012)."],
        "local_rates_age_days": 10,
    }

    json_path = pricing.generate_json_report(payload, tmp_path / "pricing.json")
    md_path = pricing.generate_markdown_report(payload, tmp_path / "pricing.md")

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["checker_version"] == pricing.CHECKER_VERSION
    markdown = md_path.read_text(encoding="utf-8")
    assert "## Summary" in markdown
    assert "Local defaults last updated 10 days ago" in markdown


def test_compare_with_previous_trend(sample_previous_report: dict) -> None:
    current_payload = {
        "check_date": "2025-12-13T00:00:00+00:00",
        "changes": {
            "increased": [
                {
                    "model": "gpt-4o",
                    "rate_type": "input",
                    "old_price": 0.0014,
                    "new_price": 0.0016,
                    "change_pct": 14.29,
                    "change_per_1m_tokens": 0.2,
                },
                {
                    "model": "gpt-4-turbo",
                    "rate_type": "output",
                    "old_price": 0.0105,
                    "new_price": 0.0115,
                    "change_pct": 9.52,
                    "change_per_1m_tokens": 1.0,
                },
            ],
            "decreased": [],
        },
    }

    trend = pricing.compare_with_previous(current_payload, sample_previous_report)

    assert trend["price_trend"] == "increasing"
    assert "gpt-4o" in trend["models_that_changed_again"]
    assert trend["time_since_last_check"] == "11 days"


def test_notify_pricing_changes_console_output(capsys: pytest.CaptureFixture[str]) -> None:
    changes = {
        "increased": [{"model": "gpt-4o", "rate_type": "input"}],
        "decreased": [],
        "new_models": ["gpt-5-mini"],
    }

    pricing.notify_pricing_changes(changes, method="console")

    captured = capsys.readouterr()
    assert "PRICING ALERT" in captured.out


def test_auto_commit_pricing_changes_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report_dir = tmp_path / "logs" / "pricing_checks"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "pricing_check_2025-12-13.json"
    report_path.write_text("{}", encoding="utf-8")

    changes = {
        "increased": [{"model": "gpt-4o", "rate_type": "input", "change_pct": 10.0}],
        "decreased": [],
        "new_models": [],
    }

    monkeypatch.setattr(pricing.shutil, "which", lambda _: "git")
    monkeypatch.setattr(pricing, "_repo_dirty", lambda _run_dir: False)

    assert pricing.auto_commit_pricing_changes([report_path], changes, run_dir=tmp_path, dry_run=True)
    output = capsys.readouterr().out
    assert "DRY RUN" in output
